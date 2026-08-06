/* eslint-disable @typescript-eslint/no-explicit-any */
declare module '@whiskeysockets/baileys' {
  export type AnyMessageContent = Record<string, any>;
  export type ConnectionState = {
    connection: 'open' | 'close' | 'connecting';
    lastDisconnect?: { error?: { output?: { statusCode?: number } }; date: Date };
    qr?: string;
    isNewLogin?: boolean;
    isOnline?: boolean;
    receivedPendingNotifications?: boolean;
  };
  export type WAMessage = {
    key: { remoteJid?: string; fromMe?: boolean; id?: string; participant?: string };
    message?: Record<string, any> | null;
    messageTimestamp?: number | Long;
    pushName?: string;
  };
  export namespace proto {
    interface IWebMessageInfo {
      key?: { remoteJid?: string; fromMe?: boolean; id?: string; participant?: string };
      message?: Record<string, any> | null;
      messageTimestamp?: number | Long;
    }
    interface Message {
      conversation?: string;
      extendedTextMessage?: { text?: string; contextInfo?: { mentionedJid?: string[] } };
      [key: string]: any;
    }
  }
  export const DisconnectReason: Record<string, number>;
  export function fetchLatestBaileysVersion(): Promise<{ version: number[]; isLatest: boolean }>;
  export function makeCacheableSignalKeyStore(store: any, logger: any): any;
  export function makeWASocket(config: Record<string, any>): any;
  export function useMultiFileAuthState(folder: string): Promise<{
    state: any;
    saveCreds: () => Promise<void>;
  }>;
  export function isJidGroup(jid: string): boolean;
  export function normalizeMessageContent(content: any): Record<string, any> | undefined;
  export function extractMessageContent(content: any): Record<string, any> | undefined;
}
