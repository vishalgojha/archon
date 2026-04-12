<script lang="ts">
    import { onMount } from 'svelte';
    import { loadConfig, getConfig, saveConfig, getApiBaseUrl } from '$lib/config';
    import PageAgentPanel from '$lib/components/PageAgent.svelte';

    let messages: { role: 'user' | 'assistant' | 'system'; content: string }[] = [
        { role: 'system', content: 'Welcome to Archon Coder. Describe what you want to build.' }
    ];
    let input = '';
    let isRunning = false;
    let ollamaModel = 'qwen2.5:3b';
    let availableModels: string[] = [];
    let browserPanelOpen = true;
    let config = loadConfig();
    let showSettings = false;

    onMount(async () => {
        window.onerror = (msg, src, line, col, err) => {
            document.dispatchEvent(new CustomEvent('archon-log', { 
                detail: { type: 'error', msg: `${msg} (${src}:${line})` } 
            }));
            return false;
        };
        await checkOllama();
    });

    async function checkOllama() {
        try {
            const baseUrl = getApiBaseUrl();
            const r = await fetch(`${baseUrl}/api/ollama/models`);
            const result = await r.json();
            if (result.models) {
                availableModels = result.models;
                ollamaModel = availableModels[0] || config.ollamaModel;
            }
        } catch (e) {
            console.error('Ollama check failed:', e);
        }
    }

    async function sendMessage() {
        if (!input.trim() || isRunning) return;
        const userMsg = input.trim();
        messages = [...messages, { role: 'user', content: userMsg }];
        input = '';
        isRunning = true;

        try {
            const baseUrl = getApiBaseUrl();
            const r = await fetch(`${baseUrl}/api/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model: ollamaModel, messages: [{ role: 'user', content: userMsg }] })
            });
            const result = await r.json();
            
            if (result.message?.content) {
                messages = [...messages, { role: 'assistant', content: result.message.content }];
            } else if (result.error) {
                messages = [...messages, { role: 'assistant', content: result.error }];
            } else {
                messages = [...messages, { role: 'assistant', content: JSON.stringify(result) }];
            }
        } catch (e: any) {
            messages = [...messages, { role: 'assistant', content: 'Error: ' + e.message }];
        }
        isRunning = false;
    }

    function clearChat() {
        messages = [{ role: 'system', content: 'Welcome to Archon Coder. Describe what you want to build.' }];
    }

    function saveSettings() {
        saveConfig(config);
        showSettings = false;
        checkOllama();
    }
</script>

<div class="app">
    <header class="topbar">
        <div class="brand">
            <span class="logo">⚡ Archon Coder</span>
        </div>
        <div class="model-select-wrapper">
            <select bind:value={ollamaModel} class="model-select">
                {#each availableModels as m}
                    <option value={m}>{m}</option>
                {/each}
            </select>
        </div>
        <div class="actions">
            <button class="toggle-btn" on:click={() => showSettings = !showSettings}>
                ⚙️ {config.backend === 'hetzner' ? 'Hetzner' : 'Local'}
            </button>
            <button class="toggle-btn" class:active={browserPanelOpen} on:click={() => browserPanelOpen = !browserPanelOpen}>
                🌐 Browser {browserPanelOpen ? '▼' : '▲'}
            </button>
        </div>
    </header>

    {#if showSettings}
        <div class="settings-panel">
            <h3>Settings</h3>
            <div class="field">
                <label>Backend</label>
                <select bind:value={config.backend}>
                    <option value="localhost">Localhost</option>
                    <option value="hetzner">Hetzner Cloud</option>
                </select>
            </div>
            {#if config.backend === 'hetzner'}
                <div class="field">
                    <label>Hetzner URL</label>
                    <input type="text" bind:value={config.hetznerUrl} placeholder="https://your-server-ip" />
                </div>
            {/if}
            <div class="field">
                <label>Ollama Model</label>
                <input type="text" bind:value={config.ollamaModel} placeholder="qwen2.5:3b" />
            </div>
            <button class="save-btn" on:click={saveSettings}>Save</button>
        </div>
    {/if}

    <main class="workspace" class:browser-open={browserPanelOpen}>
        <section class="chat-panel">
            <div class="chat-messages">
                {#each messages as msg}
                    <div class="message {msg.role}">
                        <div class="msg-role">{msg.role === 'user' ? 'You' : msg.role === 'assistant' ? 'AI' : 'System'}</div>
                        <div class="msg-content">{msg.content}</div>
                    </div>
                {/each}
                {#if isRunning}
                    <div class="message assistant">
                        <div class="msg-role">AI</div>
                        <div class="msg-content thinking">Thinking...</div>
                    </div>
                {/if}
            </div>
            <div class="chat-input">
                <input 
                    bind:value={input} 
                    on:keydown={(e) => e.key === 'Enter' && sendMessage()}
                    placeholder="Describe what you want to build..."
                    disabled={isRunning}
                />
                <button on:click={sendMessage} disabled={isRunning || !input.trim()}>
                    {isRunning ? '...' : 'Send'}
                </button>
                <button class="clear-btn" on:click={clearChat}>Clear</button>
            </div>
        </section>

        {#if browserPanelOpen}
            <section class="browser-panel">
                <PageAgentPanel {ollamaModel} />
            </section>
        {/if}
    </main>
</div>

<style>
    :global(body) {
        margin: 0;
        background: #09090b;
        color: #fafafa;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }

    .app {
        display: flex;
        flex-direction: column;
        height: 100vh;
    }

    .topbar {
        display: flex;
        align-items: center;
        padding: 12px 20px;
        border-bottom: 1px solid #27272a;
        background: #0A0A0A;
        gap: 16px;
    }

    .brand { display: flex; align-items: center; }
    .logo { font-weight: 700; font-size: 16px; color: #E8DCC8; }

    .model-select-wrapper { flex: 1; }
    .model-select {
        background: #18181b;
        border: 1px solid #3f3f46;
        color: #fafafa;
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 13px;
    }

    .actions { display: flex; gap: 8px; }
    .toggle-btn {
        background: #18181b;
        border: 1px solid #3f3f46;
        color: #a1a1aa;
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 13px;
        cursor: pointer;
    }
    .toggle-btn:hover { border-color: #52525b; }
    .toggle-btn.active { border-color: #22c55e; color: #22c55e; }

    .settings-panel {
        padding: 16px 20px;
        border-bottom: 1px solid #27272a;
        background: #0f0f11;
    }
    .settings-panel h3 { margin: 0 0 12px; font-size: 14px; }
    .field { margin-bottom: 12px; display: flex; gap: 12px; align-items: center; }
    .field label { width: 120px; font-size: 13px; color: #a1a1aa; }
    .field input, .field select { flex: 1; background: #18181b; border: 1px solid #3f3f46; color: #fafafa; padding: 8px; border-radius: 4px; }
    .save-btn { background: #22c55e; border: none; color: #09090b; padding: 8px 16px; border-radius: 4px; cursor: pointer; font-weight: 600; }

    .workspace {
        flex: 1;
        display: flex;
        overflow: hidden;
    }
    .workspace.browser-open { display: grid; grid-template-columns: 1fr 1fr; }

    .chat-panel {
        display: flex;
        flex-direction: column;
        background: #09090b;
        min-width: 0;
    }
    .browser-panel { display: flex; flex-direction: column; background: #0A0A0A; border-left: 1px solid #27272a; min-width: 0; }

    .chat-messages { flex: 1; overflow-y: auto; padding: 16px; }
    .message { display: flex; gap: 12px; margin-bottom: 16px; }
    .message.system { background: #18181b; padding: 12px 16px; border-radius: 8px; border: 1px solid #27272a; }
    .message.user { flex-direction: row-reverse; }
    .msg-role { font-weight: 600; font-size: 11px; color: #71717a; min-width: 40px; }
    .message.user .msg-role { text-align: right; }
    .message.system .msg-role { color: #22c55e; }
    .msg-content { flex: 1; font-size: 14px; line-height: 1.5; white-space: pre-wrap; }
    .message.user .msg-content { background: #18181b; padding: 12px 16px; border-radius: 12px; }
    .thinking { color: #71717a; font-style: italic; }

    .chat-input {
        display: flex;
        gap: 8px;
        padding: 16px;
        border-top: 1px solid #27272a;
    }
    .chat-input input {
        flex: 1;
        background: #18181b;
        border: 1px solid #3f3f46;
        border-radius: 8px;
        padding: 12px 16px;
        color: #fafafa;
        font-size: 14px;
    }
    .chat-input input:focus { outline: none; border-color: #22c55e; }
    .chat-input button {
        padding: 12px 20px;
        background: #22c55e;
        border: none;
        border-radius: 8px;
        color: #09090b;
        font-weight: 600;
        cursor: pointer;
    }
    .chat-input button:hover:not(:disabled) { background: #16a34a; }
    .chat-input button:disabled { opacity: 0.5; }
    .clear-btn { background: #27272a !important; color: #a1a1aa !important; }
    .clear-btn:hover { background: #3f3f46 !important; }
</style>
