import { createChannelManager } from './channels/manager.js';
import { createWhatsAppPlugin } from './channels/whatsapp/plugin.js';
import {
  assertOutboundAllowed,
  sendComposing,
  sendMessageWhatsApp,
  type WhatsAppInboundMessage,
} from './channels/whatsapp/index.js';
import { resolveRoute } from './routing/resolve-route.js';
import { resolveSessionStorePath, upsertSessionMeta } from './sessions/store.js';
import { loadGatewayConfig, type GatewayConfig } from './config.js';
import { runAgentForMessage } from './agent-runner.js';
import { cleanMarkdownForWhatsApp } from './utils.js';
import { startHeartbeatRunner } from './heartbeat/index.js';
import {
  isBotMentioned,
  recordGroupMessage,
  getAndClearGroupHistory,
  formatGroupHistoryContext,
  noteGroupMember,
  formatGroupMembersList,
} from './group/index.js';
import { AlertRouter, formatAlertForWhatsApp, formatAlertForTerminal } from './alerts/index.js';
import { parseCommand } from './commands/parser.js';
import { handleCommand } from './commands/handler.js';
import type { GroupContext } from '../agent/prompts.js';
import { appendFileSync } from 'node:fs';
import { appPath } from '../utils/paths.js';
import { getSetting } from '../utils/config.js';

const LOG_PATH = appPath('gateway-debug.log');
function debugLog(msg: string) {
  appendFileSync(LOG_PATH, `${new Date().toISOString()} ${msg}\n`);
}

export type GatewayService = {
  stop: () => Promise<void>;
  snapshot: () => Record<string, { accountId: string; running: boolean; connected?: boolean }>;
};

function elide(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen - 3) + '...';
}

async function handleInbound(cfg: GatewayConfig, inbound: WhatsAppInboundMessage, alertRouter: AlertRouter): Promise<void> {
  const bodyPreview = elide(inbound.body.replace(/\n/g, ' '), 50);
  const isGroup = inbound.chatType === 'group';
  console.log(`Inbound message ${inbound.from} (${inbound.chatType}, ${inbound.body.length} chars): "${bodyPreview}"`);
  debugLog(`[gateway] handleInbound from=${inbound.from} isGroup=${isGroup} body="${inbound.body.slice(0, 30)}..."`);

  // --- Group-specific: track member, check mention gating ---
  if (isGroup) {
    noteGroupMember(inbound.chatId, inbound.senderId, inbound.senderName);

    const mentioned = isBotMentioned({
      mentionedJids: inbound.mentionedJids,
      selfJid: inbound.selfJid,
      selfLid: inbound.selfLid,
      selfE164: inbound.selfE164,
      body: inbound.body,
    });
    debugLog(`[gateway] group mention check: mentioned=${mentioned}`);

    if (!mentioned) {
      // Buffer the message for future context but don't reply
      recordGroupMessage(inbound.chatId, {
        senderName: inbound.senderName ?? inbound.senderId,
        senderId: inbound.senderId,
        body: inbound.body,
        timestamp: inbound.timestamp ?? Date.now(),
      });
      debugLog(`[gateway] group message buffered (no mention), skipping reply`);
      return;
    }
  }

  // --- Routing: use chatId for groups (group JID), senderId for DMs ---
  const peerId = isGroup ? inbound.chatId : inbound.senderId;
  const route = resolveRoute({
    cfg,
    channel: 'whatsapp',
    accountId: inbound.accountId,
    peer: { kind: inbound.chatType, id: peerId },
  });

  const storePath = resolveSessionStorePath(route.agentId);
  upsertSessionMeta({
    storePath,
    sessionKey: route.sessionKey,
    channel: 'whatsapp',
    to: inbound.from,
    accountId: route.accountId,
    agentId: route.agentId,
  });

  // --- Command interception: parse message as command before falling through to agent ---
  const intent = parseCommand(inbound.body);
  if (intent.type !== 'none') {
    debugLog(`[gateway] command intercepted: ${intent.type}`);
    try {
      const reply = await handleCommand(intent, alertRouter, route.sessionKey);
      if (reply) {
        const outboundTarget = isGroup ? inbound.chatId : inbound.replyToJid;
        try {
          assertOutboundAllowed({ to: outboundTarget, accountId: inbound.accountId });
        } catch (error) {
          const msg = error instanceof Error ? error.message : String(error);
          debugLog(`[gateway] command outbound BLOCKED: ${msg}`);
          return;
        }
        if (isGroup) {
          await inbound.reply(reply);
        } else {
          await sendMessageWhatsApp({ to: inbound.replyToJid, body: reply, accountId: inbound.accountId });
        }
        console.log(`Command '${intent.type}' replied (${reply.length} chars)`);
        debugLog(`[gateway] command reply sent`);
        return;
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.log(`Command error: ${msg}`);
      debugLog(`[gateway] command ERROR: ${msg}`);
    }
  }

  // Start typing indicator loop to keep it alive during long agent runs
  const TYPING_INTERVAL_MS = 5000; // Refresh every 5 seconds
  let typingTimer: ReturnType<typeof setInterval> | undefined;

  const startTypingLoop = async () => {
    // For groups, use inbound.sendComposing directly (bypasses outbound strict checks)
    if (isGroup) {
      await inbound.sendComposing();
      typingTimer = setInterval(() => { void inbound.sendComposing(); }, TYPING_INTERVAL_MS);
    } else {
      await sendComposing({ to: inbound.replyToJid, accountId: inbound.accountId });
      typingTimer = setInterval(() => {
        void sendComposing({ to: inbound.replyToJid, accountId: inbound.accountId });
      }, TYPING_INTERVAL_MS);
    }
  };

  const stopTypingLoop = () => {
    if (typingTimer) {
      clearInterval(typingTimer);
      typingTimer = undefined;
    }
  };

  try {
    // Defense-in-depth: verify outbound destination is allowed before any messaging
    // For groups, use chatId (the group JID); for DMs, use replyToJid
    const outboundTarget = isGroup ? inbound.chatId : inbound.replyToJid;
    try {
      assertOutboundAllowed({ to: outboundTarget, accountId: inbound.accountId });
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      debugLog(`[gateway] outbound BLOCKED: ${msg}`);
      console.log(msg);
      return;
    }

    await startTypingLoop();

    // --- Build query: for groups, include buffered history context ---
    let query = inbound.body;
    let groupContext: GroupContext | undefined;

    if (isGroup) {
      const history = getAndClearGroupHistory(inbound.chatId);
      query = formatGroupHistoryContext({
        history,
        currentSenderName: inbound.senderName ?? inbound.senderId,
        currentSenderId: inbound.senderId,
        currentBody: inbound.body,
      });
      debugLog(`[gateway] group query with ${history.length} history entries`);

      const membersList = formatGroupMembersList({
        groupId: inbound.chatId,
        participants: inbound.groupParticipants,
      });
      groupContext = {
        groupName: inbound.groupSubject,
        membersList: membersList || undefined,
        activationMode: 'mention',
      };
    }

    console.log(`Processing message with agent...`);
    debugLog(`[gateway] running agent for session=${route.sessionKey}`);
    const startedAt = Date.now();
    const model = getSetting('modelId', 'gpt-5.4') as string;
    const modelProvider = getSetting('provider', 'openai') as string;
    const answer = await runAgentForMessage({
      sessionKey: route.sessionKey,
      query,
      model,
      modelProvider,
      channel: 'whatsapp',
      groupContext,
    });
    const durationMs = Date.now() - startedAt;
    debugLog(`[gateway] agent answer length=${answer.length}`);

    // Stop typing loop before sending reply
    stopTypingLoop();

    if (answer.trim()) {
      const cleanedAnswer = cleanMarkdownForWhatsApp(answer);

      if (isGroup) {
        // For groups, use inbound.reply() directly (bypasses outbound strict E.164 checks)
        debugLog(`[gateway] sending group reply to ${inbound.chatId}`);
        await inbound.reply(cleanedAnswer);
      } else {
        debugLog(`[gateway] sending reply to ${inbound.replyToJid}`);
        await sendMessageWhatsApp({
          to: inbound.replyToJid,
          body: cleanedAnswer,
          accountId: inbound.accountId,
        });
      }
      console.log(`Sent reply (${answer.length} chars, ${durationMs}ms)`);
      debugLog(`[gateway] reply sent`);
    } else {
      console.log(`Agent returned empty response (${durationMs}ms)`);
      debugLog(`[gateway] empty answer, not sending`);
    }
  } catch (err) {
    stopTypingLoop();
    const msg = err instanceof Error ? err.message : String(err);
    console.log(`Error: ${msg}`);
    debugLog(`[gateway] ERROR: ${msg}`);
  }
}

export async function startGateway(params: { configPath?: string } = {}): Promise<GatewayService> {
  const cfg = loadGatewayConfig(params.configPath);

  // --- Alert Router setup ---
  const alertRouter = new AlertRouter();

  // Terminal handler
  alertRouter.registerChannel('terminal', async (alert) => {
    console.log(formatAlertForTerminal(alert));
  });

  // WhatsApp handler
  alertRouter.registerChannel('whatsapp', async (alert, target) => {
    if (!target) return;
    const formatted = formatAlertForWhatsApp(alert);
    try {
      await sendMessageWhatsApp({
        to: target,
        body: formatted,
        accountId: cfg.gateway.accountId,
      });

      // Set pending approval for edge alerts
      if (alert.alertType === 'EDGE_DETECTED') {
        alertRouter.setPending(target, {
          ticker: alert.ticker,
          alertId: crypto.randomUUID(),
          edge: alert.edge,
          createdAt: Date.now(),
          sessionKey: target,
        });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.log(`[AlertRouter] WhatsApp send failed: ${msg}`);
    }
  });

  const plugin = createWhatsAppPlugin({
    loadConfig: () => loadGatewayConfig(params.configPath),
    onMessage: async (inbound) => {
      const current = loadGatewayConfig(params.configPath);
      await handleInbound(current, inbound, alertRouter);
    },
  });
  const manager = createChannelManager({
    plugin,
    loadConfig: () => loadGatewayConfig(params.configPath),
  });
  await manager.startAll();

  const heartbeat = startHeartbeatRunner({ configPath: params.configPath });

  return {
    stop: async () => {
      heartbeat.stop();
      await manager.stopAll();
    },
    snapshot: () => manager.getSnapshot(),
  };
}

