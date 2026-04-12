<script lang="ts">
    import { invoke } from '$lib/tauri-api';

    export let showFileTree = false;
    export let showConsciousness = false;
    let modelLabel = 'ollama';

    async function toggleModel() {
        const next = modelLabel === 'ollama' ? 'groq' : 'ollama';
        try {
            await invoke('switch_model', { model: next });
            modelLabel = next;
        } catch (e) {
            console.error(e);
        }
    }
</script>

<header class="topbar">
    <div class="left">
        <span class="logo">âš¡ Archon Coder</span>
        <button class="model-btn" on:click={toggleModel}>{modelLabel}</button>
    </div>
    <div class="right">
        <button class:active={showFileTree} on:click={() => showFileTree = !showFileTree}>ðŸ“ Files</button>
        <button class:active={showConsciousness} on:click={() => showConsciousness = !showConsciousness}>ðŸ§  Mind</button>
    </div>
</header>

<style>
    .topbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 16px;
        height: 48px;
        background: var(--bg-secondary);
        border-bottom: 1px solid var(--border);
        z-index: 100;
    }
    .left, .right { display: flex; align-items: center; gap: 12px; }
    .logo { font-weight: 700; font-size: 16px; color: var(--blue); letter-spacing: -0.5px; }
    .model-btn {
        background: var(--bg-tertiary);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 2px 10px;
        font-size: 11px;
        font-family: monospace;
        color: var(--cyan);
        text-transform: uppercase;
        cursor: pointer;
    }
    .model-btn:hover { border-color: var(--blue); }
    .right button {
        background: var(--bg-tertiary);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 6px 12px;
        font-size: 12px;
        color: var(--text);
        cursor: pointer;
    }
    .right button:hover { background: var(--border); border-color: var(--blue); }
    .right button.active { border-color: var(--green); color: var(--green); }
</style>
