<script lang="ts">
    import { onMount } from 'svelte';
    import { getApiBaseUrl, loadConfig } from '$lib/config';

    export let ollamaModel: string = 'qwen2.5:3b';

    let status = 'idle';
    let taskInput = '';
    let isRunning = false;
    let error: string | null = null;
    let history: { role: string; content: string }[] = [];
    let browserUrl = '';
    let pageContent = '';
    let config = loadConfig();

    onMount(async () => {
        config = loadConfig();
    });

    async function checkOllama() {
        try {
            const baseUrl = getApiBaseUrl();
            const r = await fetch(`${baseUrl}/api/ollama/models`);
            const result = await r.json();
            if (result.models) {
                status = 'ready';
            }
        } catch (e) {
            status = 'error';
            error = 'Cannot connect to backend';
        }
    }

    async function navigateUrl() {
        if (!browserUrl.trim()) return;
        status = 'loading';
        
        try {
            const baseUrl = getApiBaseUrl();
            const r = await fetch(`${baseUrl}/api/command`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: 'browser', text: `Navigate to ${browserUrl}` })
            });
            const result = await r.json();
            
            if (result.output) {
                status = 'ready';
            } else {
                error = result.error || 'Navigation failed';
                status = 'error';
            }
        } catch (e: any) {
            error = e.message;
            status = 'error';
        }
    }

    async function executeTask() {
        if (!taskInput.trim() || isRunning || status !== 'ready') return;

        const prompt = taskInput.trim();
        history = [...history, { role: 'user', content: prompt }];
        taskInput = '';
        isRunning = true;
        status = 'running';

        try {
            const baseUrl = getApiBaseUrl();
            const r = await fetch(`${baseUrl}/api/command`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    session_id: 'browser', 
                    text: `Browser task: ${prompt}. Use tools to interact with the browser.` 
                })
            });
            const result = await r.json();
            
            if (result.output) {
                history = [...history, { role: 'assistant', content: result.output }];
            } else {
                history = [...history, { role: 'assistant', content: result.error || 'No response' }];
            }
        } catch (e: any) {
            history = [...history, { role: 'assistant', content: 'Error: ' + e.message }];
        }

        isRunning = false;
        status = 'ready';
    }

    function clearHistory() {
        history = [];
    }
</script>

<div class="page-agent-panel">
    <div class="panel-header">
        <h3>🌐 Browser Agent</h3>
        <div class="header-actions">
            <span class="cdp-status" class:connected={status === 'ready'} class:error={status === 'error'}>
                {status}
            </span>
        </div>
    </div>

    <div class="url-bar">
        <input 
            type="text" 
            bind:value={browserUrl} 
            placeholder="Enter URL to navigate..."
            on:keydown={(e) => e.key === 'Enter' && navigateUrl()}
        />
        <button on:click={navigateUrl}>Go</button>
    </div>

    {#if error}
        <div class="error-message">{error}</div>
    {/if}

    <div class="chat-history">
        {#if history.length === 0}
            <div class="empty">
                Enter a task like "go to github.com" to control the browser via the AI agent.
            </div>
        {:else}
            {#each history as msg}
                <div class="message {msg.role}">
                    <div class="msg-role">{msg.role === 'user' ? '>' : '<'}</div>
                    <div class="msg-content">{msg.content}</div>
                </div>
            {/each}
        {/if}
    </div>

    <div class="input-bar">
        <input 
            type="text" 
            bind:value={taskInput} 
            placeholder={status === 'ready' ? "E.g., click search and type 'react'" : "Connecting..."}
            on:keydown={(e) => e.key === 'Enter' && executeTask()}
            disabled={isRunning || status !== 'ready'}
        />
        <button on:click={executeTask} disabled={isRunning || status !== 'ready' || !taskInput.trim()}>
            {isRunning ? '...' : 'Run'}
        </button>
    </div>
</div>

<style>
    .page-agent-panel {
        display: flex;
        flex-direction: column;
        height: 100%;
        background: #0A0A0A;
    }

    .panel-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 14px;
        border-bottom: 1px solid #27272a;
    }

    .panel-header h3 {
        font-size: 13px;
        font-weight: 600;
        color: #fafafa;
        margin: 0;
    }

    .header-actions { display: flex; align-items: center; gap: 8px; }

    .cdp-status {
        font-size: 11px;
        padding: 3px 10px;
        border-radius: 4px;
        background: #27272a;
        color: #71717a;
    }
    .cdp-status.connected { background: rgba(34, 197, 94, 0.2); color: #22c55e; }
    .cdp-status.error { background: rgba(239, 68, 68, 0.2); color: #ef4444; }

    .url-bar {
        display: flex;
        gap: 8px;
        padding: 8px 12px;
        border-bottom: 1px solid #27272a;
    }

    .url-bar input {
        flex: 1;
        background: #18181b;
        border: 1px solid #3f3f46;
        border-radius: 4px;
        padding: 6px 10px;
        color: #fafafa;
        font-size: 12px;
    }

    .url-bar button {
        padding: 6px 12px;
        background: #27272a;
        border: none;
        border-radius: 4px;
        color: #a1a1aa;
        font-size: 11px;
        cursor: pointer;
    }

    .error-message {
        background: rgba(239, 68, 68, 0.1);
        border-bottom: 1px solid #ef4444;
        color: #ef4444;
        padding: 8px 12px;
        font-size: 12px;
    }

    .chat-history {
        flex: 1;
        overflow-y: auto;
        padding: 8px;
    }

    .empty {
        text-align: center;
        color: #52525b;
        padding: 24px;
        font-size: 12px;
    }

    .message {
        display: flex;
        gap: 8px;
        padding: 6px 8px;
        margin-bottom: 4px;
        border-radius: 4px;
    }

    .message.user { background: #18181b; }
    .message.assistant { background: #1c1c1f; }

    .msg-role {
        font-weight: 600;
        font-family: monospace;
        color: #71717a;
        font-size: 11px;
        min-width: 16px;
    }

    .msg-content {
        flex: 1;
        font-size: 12px;
        color: #d4d4d8;
        white-space: pre-wrap;
        word-break: break-word;
    }

    .input-bar {
        display: flex;
        gap: 8px;
        padding: 10px 12px;
        border-top: 1px solid #27272a;
    }

    .input-bar input {
        flex: 1;
        background: #18181b;
        border: 1px solid #3f3f46;
        border-radius: 6px;
        padding: 10px 12px;
        color: #fafafa;
        font-size: 13px;
    }

    .input-bar input:focus { outline: none; border-color: #22c55e; }
    .input-bar input:disabled { opacity: 0.5; }

    .input-bar button {
        padding: 10px 16px;
        background: #22c55e;
        border: none;
        border-radius: 6px;
        color: #09090b;
        font-weight: 600;
        font-size: 12px;
        cursor: pointer;
    }

    .input-bar button:hover:not(:disabled) { background: #16a34a; }
    .input-bar button:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
