/**
 * tauri-api.ts — Tauri invoke wrapper with dev-mode fallback.
 * In dev mode (no __TAURI__ global), falls back to HTTP fetch calls.
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function invoke<T>(cmd: string, args: Record<string, unknown> = {}): Promise<T> {
    const w = window as any;
    if (w.__TAURI__?.core?.invoke) {
        return w.__TAURI__.core.invoke(cmd, args);
    }
    return devFallback(cmd, args) as Promise<T>;
}

const SIDECAR = 'http://localhost:18765';

// --- Advanced Feature API Wrappers ---

export async function generateTests(cwd: string, filePath: string, framework: string) {
    return invoke<any>('generate_tests', { cwd, file_path: filePath, framework });
}

export async function generateDocs(filePath: string, style: string) {
    return invoke<any>('generate_docs', { file_path: filePath, style });
}

export async function reviewCode(cwd: string, filePath: string) {
    return invoke<any>('review_code', { cwd, file_path: filePath });
}

export async function securityScan(cwd: string) {
    return invoke<any>('security_scan', { cwd });
}

export async function optimizeCode(filePath: string) {
    return invoke<any>('optimize_code', { file_path: filePath });
}

export async function autoFix(cwd: string, errorOutput: string) {
    return invoke<any>('auto_fix', { cwd, error_output: errorOutput });
}

export async function scheduleTask(name: string, cronExpr: string, command: string) {
    return invoke<any>('schedule_task', { name, cron_expr: cronExpr, command });
}

export async function listScheduledTasks() {
    return invoke<any>('list_scheduled_tasks', {});
}

export async function savePreference(key: string, value: any) {
    return invoke<any>('save_preference', { key, value });
}

export async function getPreference(key: string) {
    return invoke<any>('get_preference', { key });
}

export async function learnPattern(patterns: any) {
    return invoke<any>('learn_pattern', { patterns });
}

export async function designArchitecture(requirements: string, language: string) {
    return invoke<any>('design_architecture', { requirements, language });
}

export async function generateSchema(tableName: string, fields: any[], dbType: string) {
    return invoke<any>('generate_schema', { table_name: tableName, fields, db_type: dbType });
}

export async function generateMigration(fromSchema: string, toSchema: string, dbType: string) {
    return invoke<any>('generate_migration', { from_schema: fromSchema, to_schema: toSchema, db_type: dbType });
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function devFallback(cmd: string, args: Record<string, any>): Promise<any> {
    const map: Record<string, () => Promise<string>> = {
        async list_sessions() {
            try {
                const r = await fetch(`${SIDECAR}/health`);
                return JSON.stringify({ ok: true, data: [] });
            } catch { return JSON.stringify({ ok: true, data: [] }); }
        },
        async create_session() {
            return JSON.stringify({ ok: true, session_id: 'dev_' + Date.now(), data: { id: 'dev_' + Date.now(), name: args.name, mode: args.mode } });
        },
        async get_session() {
            return JSON.stringify({ ok: true, data: { id: args.sessionId, name: 'Dev Session', mode: 'isolated', message_count: 0, last_active: new Date().toISOString() } });
        },
        async delete_session() {
            return JSON.stringify({ ok: true });
        },
        async send_command() {
            try {
                const r = await fetch(`${SIDECAR}/api/command`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session_id: args.sessionId || 'dev', text: args.text }),
                });
                return JSON.stringify(await r.json());
            } catch (e: unknown) {
                const msg = e instanceof Error ? e.message : String(e);
                return JSON.stringify({ ok: false, output: `Sidecar not running. Start with: python sidecar/main.py\n\nError: ${msg}` });
            }
        },
        async get_consciousness() {
            try {
                const r = await fetch(`${SIDECAR}/api/consciousness/${args.sessionId || 'dev'}`);
                return JSON.stringify(await r.json());
            } catch { return JSON.stringify({ events: [], narrative: 'No events yet.' }); }
        },
        async switch_model() {
            try {
                const r = await fetch(`${SIDECAR}/api/model`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ model: args.model }),
                });
                return JSON.stringify(await r.json());
            } catch { return JSON.stringify({ ok: false, error: 'Sidecar not running' }); }
        },
        async get_model() {
            try {
                const r = await fetch(`${SIDECAR}/api/model`);
                return JSON.stringify(await r.json());
            } catch { return JSON.stringify({ model: 'ollama' }); }
        },
        async list_directory() {
            return JSON.stringify({ ok: false, error: 'Use sidecar /file command' });
        },
        async read_file() {
            return JSON.stringify({ ok: false, error: 'Use sidecar /file command' });
        },
    };

    const fn = map[cmd];
    if (!fn) {
        console.warn(`[dev] No fallback for: ${cmd}`);
        return JSON.stringify({ ok: false, error: `No dev fallback: ${cmd}` });
    }

    try {
        return await fn();
    } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        return JSON.stringify({ ok: false, error: msg });
    }
}
