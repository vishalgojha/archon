/**
 * page-agent-bridge.ts — CDP browser automation with zod v4 validation.
 *
 * Integrates with Chrome DevTools Protocol (ws://127.0.0.1:9222)
 * to provide full page automation: navigate, click, type, extract, scroll, wait, screenshot.
 *
 * All actions are validated with zod v4 schemas before execution.
 */

import { z } from 'zod';

// ─── Zod v4 Action Schemas ──────────────────────────────────────────────

const NavigateAction = z.object({
    type: z.literal('navigate'),
    url: z.string().url().or(z.string().min(1)),
});

const ClickAction = z.object({
    type: z.literal('click'),
    selector: z.string().min(1),
    timeout: z.number().int().positive().optional().default(5000),
});

const TypeAction = z.object({
    type: z.literal('type'),
    selector: z.string().min(1),
    text: z.string(),
    clear: z.boolean().optional().default(true),
});

const ExtractAction = z.object({
    type: z.literal('extract'),
    selector: z.string().min(1),
    attribute: z.string().optional().default('innerText'),
});

const ScrollAction = z.object({
    type: z.literal('scroll'),
    direction: z.enum(['up', 'down', 'left', 'right']),
    amount: z.number().int().positive().optional().default(500),
});

const WaitAction = z.object({
    type: z.literal('wait'),
    selector: z.string().min(1),
    timeout: z.number().int().positive().optional().default(5000),
});

const ScreenshotAction = z.object({
    type: z.literal('screenshot'),
    format: z.enum(['png', 'jpeg', 'webp']).optional().default('png'),
    fullPage: z.boolean().optional().default(false),
});

const EvalAction = z.object({
    type: z.literal('eval'),
    expression: z.string().min(1),
});

const AnyAction = z.discriminatedUnion('type', [
    NavigateAction,
    ClickAction,
    TypeAction,
    ExtractAction,
    ScrollAction,
    WaitAction,
    ScreenshotAction,
    EvalAction,
]);

const ActionPlan = z.object({
    url: z.string().optional(),
    actions: z.array(AnyAction),
    waitForNavigation: z.boolean().optional().default(true),
});

export type CDPAction = z.infer<typeof AnyAction>;
export type CDPActionPlan = z.infer<typeof ActionPlan>;
export type CDPActionResult = {
    ok: boolean;
    action: string;
    data?: unknown;
    error?: string;
    duration: number;
};

// ─── CDP Bridge ──────────────────────────────────────────────────────────

export class PageAgentBridge {
    private cdpBaseUrl = 'http://127.0.0.1:9222';
    private wsUrl: string | null = null;
    private ws: WebSocket | null = null;
    private actionHistory: CDPActionResult[] = [];
    private msgId = 0;

    /** Check if Chrome is running with --remote-debugging-port=9222 */
    async isAvailable(): Promise<boolean> {
        try {
            const resp = await fetch(`${this.cdpBaseUrl}/json`);
            return resp.ok;
        } catch {
            return false;
        }
    }

    /** Get the WebSocket URL for the first page target */
    async connect(): Promise<string> {
        if (this.wsUrl) return this.wsUrl;

        const resp = await fetch(`${this.cdpBaseUrl}/json`);
        if (!resp.ok) throw new Error(`CDP unavailable: ${resp.status}`);

        const targets = await resp.json() as Array<{
            webSocketDebuggerUrl: string;
            type: string;
            url: string;
        }>;

        const page = targets.find(t => t.type === 'page');
        if (!page) throw new Error('No page target found');

        this.wsUrl = page.webSocketDebuggerUrl;
        return this.wsUrl;
    }

    /** Get or create a WebSocket connection */
    private async getWs(): Promise<WebSocket> {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) return this.ws;

        const wsUrl = await this.connect();
        this.ws = new WebSocket(wsUrl);

        return new Promise((resolve, reject) => {
            const timeout = setTimeout(() => reject(new Error('CDP WebSocket timeout')), 10000);
            this.ws!.onopen = () => { clearTimeout(timeout); resolve(this.ws!); };
            this.ws!.onerror = (e) => { clearTimeout(timeout); reject(e); };
        });
    }

    /** Send a CDP command and wait for response */
    private async sendCdp(method: string, params: Record<string, unknown> = {}): Promise<unknown> {
        const ws = await this.getWs();
        const id = ++this.msgId;

        return new Promise((resolve, reject) => {
            const timeout = setTimeout(() => reject(new Error(`CDP timeout: ${method}`)), 15000);

            const handler = (event: MessageEvent) => {
                try {
                    const msg = JSON.parse(event.data as string);
                    if (msg.id === id) {
                        clearTimeout(timeout);
                        ws.removeEventListener('message', handler);
                        if (msg.error) {
                            reject(new Error(msg.error.message));
                        } else {
                            resolve(msg.result);
                        }
                    }
                } catch { /* ignore parse errors */ }
            };

            ws.addEventListener('message', handler);
            ws.send(JSON.stringify({ id, method, params }));
        });
    }

    /** Validate and execute a single CDP action */
    async execute(action: CDPAction): Promise<CDPActionResult> {
        const start = Date.now();
        const validated = AnyAction.parse(action);

        try {
            let result: CDPActionResult;

            switch (validated.type) {
                case 'navigate':
                    result = await this.navigate(validated.url);
                    break;
                case 'click':
                    result = await this.click(validated.selector, validated.timeout);
                    break;
                case 'type':
                    result = await this.type(validated.selector, validated.text, validated.clear);
                    break;
                case 'extract':
                    result = await this.extract(validated.selector, validated.attribute);
                    break;
                case 'scroll':
                    result = await this.scroll(validated.direction, validated.amount);
                    break;
                case 'wait':
                    result = await this.wait(validated.selector, validated.timeout);
                    break;
                case 'screenshot':
                    result = await this.screenshot(validated.format, validated.fullPage);
                    break;
                case 'eval':
                    result = await this.eval(validated.expression);
                    break;
                default:
                    throw new Error(`Unknown action type: ${(validated as { type: string }).type}`);
            }

            this.actionHistory.push(result);
            return result;
        } catch (e: unknown) {
            const errorResult: CDPActionResult = {
                ok: false,
                action: validated.type,
                error: e instanceof Error ? e.message : String(e),
                duration: Date.now() - start,
            };
            this.actionHistory.push(errorResult);
            return errorResult;
        }
    }

    /** Execute a full action plan */
    async executePlan(plan: unknown): Promise<CDPActionResult[]> {
        const validated = ActionPlan.parse(plan);
        const results: CDPActionResult[] = [];

        // Navigate first if URL provided
        if (validated.url) {
            const navResult = await this.navigate(validated.url);
            results.push(navResult);
            if (validated.waitForNavigation) {
                await this.sleep(2000);
            }
        }

        // Execute actions
        for (const action of validated.actions) {
            const result = await this.execute(action);
            results.push(result);
            await this.sleep(300);
        }

        return results;
    }

    // ─── CDP Actions ─────────────────────────────────────────────────────

    async navigate(url: string): Promise<CDPActionResult> {
        const start = Date.now();
        const fullUrl = url.startsWith('http') ? url : `https://${url}`;
        const result = await this.sendCdp('Page.navigate', { url: fullUrl });
        return { ok: true, action: 'navigate', data: result, duration: Date.now() - start };
    }

    async click(selector: string, timeout = 5000): Promise<CDPActionResult> {
        const start = Date.now();
        const nodeId = await this.findElement(selector, timeout);
        if (!nodeId) {
            return { ok: false, action: 'click', error: `Element not found: ${selector}`, duration: Date.now() - start };
        }

        // Get box model for center coordinates
        const model = await this.sendCdp('DOM.getBoxModel', { nodeId }) as { model: { content: number[] } };
        const [x1, y1, x2, y2] = model.model.content;
        const x = (x1 + x2) / 2;
        const y = (y1 + y2) / 2;

        await this.sendCdp('Input.dispatchMouseEvent', {
            type: 'mousePressed',
            button: 'left',
            x, y,
            clickCount: 1,
        });
        await this.sleep(50);
        await this.sendCdp('Input.dispatchMouseEvent', {
            type: 'mouseReleased',
            button: 'left',
            x, y,
            clickCount: 1,
        });

        return { ok: true, action: 'click', data: { selector, x, y }, duration: Date.now() - start };
    }

    async type(selector: string, text: string, clear = true): Promise<CDPActionResult> {
        const start = Date.now();
        const nodeId = await this.findElement(selector);
        if (!nodeId) {
            return { ok: false, action: 'type', error: `Element not found: ${selector}`, duration: Date.now() - start };
        }

        if (clear) {
            await this.eval(`
                const el = document.querySelector('${selector.replace(/'/g, "\\'")}');
                if (el) { (el as HTMLInputElement).value = ''; el.dispatchEvent(new Event('input', { bubbles: true })); }
            `);
        }

        // Type character by character
        for (const char of text) {
            await this.sendCdp('Input.dispatchKeyEvent', {
                type: 'char',
                text: char,
            });
        }

        return { ok: true, action: 'type', data: { selector, text }, duration: Date.now() - start };
    }

    async extract(selector: string, attribute = 'innerText'): Promise<CDPActionResult> {
        const start = Date.now();
        const result = await this.eval(`
            const el = document.querySelector('${selector.replace(/'/g, "\\'")}');
            el ? el[${JSON.stringify(attribute)}] : null;
        `);
        return { ok: true, action: 'extract', data: { selector, value: result }, duration: Date.now() - start };
    }

    async scroll(direction: 'up' | 'down' | 'left' | 'right', amount = 500): Promise<CDPActionResult> {
        const start = Date.now();
        const deltas: Record<string, [number, number]> = {
            down: [0, amount], up: [0, -amount],
            right: [amount, 0], left: [-amount, 0],
        };
        const [dx, dy] = deltas[direction] || [0, amount];
        await this.sendCdp('Input.dispatchMouseEvent', {
            type: 'mouseWheel',
            x: 0, y: 0,
            deltaX: dx, deltaY: dy,
        });
        return { ok: true, action: 'scroll', data: { direction, amount }, duration: Date.now() - start };
    }

    async wait(selector: string, timeout = 5000): Promise<CDPActionResult> {
        const start = Date.now();
        const result = await this.eval(`
            new Promise((resolve) => {
                const el = document.querySelector('${selector.replace(/'/g, "\\'")}');
                if (el) { resolve(true); return; }
                const observer = new MutationObserver(() => {
                    const el = document.querySelector('${selector.replace(/'/g, "\\'")}');
                    if (el) { observer.disconnect(); resolve(true); }
                });
                observer.observe(document.body, { childList: true, subtree: true });
                setTimeout(() => { observer.disconnect(); resolve(false); }, ${timeout});
            })
        `);
        return { ok: !!result, action: 'wait', data: { selector, found: result }, duration: Date.now() - start };
    }

    async screenshot(format: 'png' | 'jpeg' | 'webp' = 'png', fullPage = false): Promise<CDPActionResult> {
        const start = Date.now();
        const result = await this.sendCdp('Page.captureScreenshot', {
            format,
            captureBeyondViewport: fullPage,
        }) as { data: string };
        return { ok: true, action: 'screenshot', data: { format, dataLength: result.data.length }, duration: Date.now() - start };
    }

    async eval(expression: string): Promise<CDPActionResult> {
        const start = Date.now();
        const result = await this.sendCdp('Runtime.evaluate', {
            expression,
            returnByValue: true,
            awaitPromise: true,
        }) as { result: { value?: unknown; exceptionDetails?: unknown } };

        if (result.exceptionDetails) {
            return { ok: false, action: 'eval', error: JSON.stringify(result.exceptionDetails), duration: Date.now() - start };
        }
        return { ok: true, action: 'eval', data: result.result?.value, duration: Date.now() - start };
    }

    // ─── Helpers ─────────────────────────────────────────────────────────

    private async findElement(selector: string, timeout = 5000): Promise<number | null> {
        const start = Date.now();
        while (Date.now() - start < timeout) {
            try {
                const result = await this.sendCdp('DOM.querySelector', {
                    nodeId: 1,
                    selector,
                }) as { nodeId: number };
                if (result.nodeId) return result.nodeId;
            } catch { /* retry */ }
            await this.sleep(200);
        }
        return null;
    }

    private sleep(ms: number) {
        return new Promise(r => setTimeout(r, ms));
    }

    /** Get action history */
    getHistory(): CDPActionResult[] {
        return [...this.actionHistory];
    }

    /** Clear history */
    clearHistory() {
        this.actionHistory = [];
    }

    /** Disconnect WebSocket */
    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
            this.wsUrl = null;
        }
    }
}

// Singleton
export const pageAgent = new PageAgentBridge();
