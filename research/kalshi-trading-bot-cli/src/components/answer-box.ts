import { Container, Markdown, Spacer, type TUI } from '@mariozechner/pi-tui';
import { formatResponse } from '../utils/markdown-table.js';
import { markdownTheme, theme } from '../theme.js';

const SPINNER_FRAMES = ['⣾', '⣽', '⣻', '⢿', '⡿', '⣟', '⣯', '⣷'];
const SPINNER_INTERVAL_MS = 80;

export class AnswerBoxComponent extends Container {
  private readonly body: Markdown;
  private value = '';
  private spinnerInterval: ReturnType<typeof setInterval> | null = null;
  private spinnerFrame = 0;
  private tui: TUI | null = null;

  constructor(initialText = '') {
    super();
    this.addChild(new Spacer(1));
    this.body = new Markdown('', 0, 0, markdownTheme, { color: (line) => line });
    this.addChild(this.body);
    this.setText(initialText);
  }

  setText(text: string) {
    this.value = text;
    this.render_();
  }

  /** Start an animated spinner prefix. Call stopSpinner() when done. */
  startSpinner(tui: TUI) {
    this.tui = tui;
    this.spinnerFrame = 0;
    if (this.spinnerInterval) return;
    this.spinnerInterval = setInterval(() => {
      this.spinnerFrame = (this.spinnerFrame + 1) % SPINNER_FRAMES.length;
      this.render_();
      this.tui?.requestRender();
    }, SPINNER_INTERVAL_MS);
  }

  /** Stop the spinner and revert to static ⏺ prefix. */
  stopSpinner() {
    if (this.spinnerInterval) {
      clearInterval(this.spinnerInterval);
      this.spinnerInterval = null;
    }
    this.render_();
  }

  private render_() {
    const rendered = formatResponse(this.value);
    const normalized = rendered.replace(/^\n+/, '');
    const prefix = this.spinnerInterval
      ? theme.primary(SPINNER_FRAMES[this.spinnerFrame])
      : theme.primary('⏺');
    this.body.setText(`${prefix}\n${normalized}`);
  }
}
