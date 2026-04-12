<script lang="ts">
    import { onMount, onDestroy } from 'svelte';

    export let onClose: () => void = () => {};

    let logs: { time: string; type: string; msg: string }[] = [];

    function addLog(e: CustomEvent) {
        const { type, msg } = e.detail;
        logs = [...logs, { 
            time: new Date().toLocaleTimeString(), 
            type, 
            msg 
        }];
    }

    onMount(() => {
        document.addEventListener('archon-log', addLog as EventListener);
    });

    onDestroy(() => {
        document.removeEventListener('archon-log', addLog as EventListener);
    });
</script>

<div class="log-panel">
    <div class="header">
        <span>Logs</span>
        <button on:click={onClose}>×</button>
    </div>
    <div class="content">
        {#if logs.length === 0}
            <div class="empty">No logs yet...</div>
        {:else}
            {#each logs as log}
                <div class="log-entry {log.type}">
                    <span class="time">{log.time}</span>
                    <span class="type">[{log.type}]</span>
                    <span class="msg">{log.msg}</span>
                </div>
            {/each}
        {/if}
    </div>
</div>

<style>
    .log-panel {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        max-height: 200px;
        background: #18181b;
        border-top: 1px solid #27272a;
        display: flex;
        flex-direction: column;
        z-index: 1000;
    }
    .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 16px;
        background: #09090b;
        border-bottom: 1px solid #27272a;
    }
    .header span {
        font-size: 12px;
        font-weight: 600;
        color: #fafafa;
    }
    .header button {
        background: transparent;
        border: none;
        color: #71717a;
        font-size: 18px;
        cursor: pointer;
    }
    .content {
        overflow-y: auto;
        padding: 8px;
        font-family: monospace;
        font-size: 11px;
    }
    .empty {
        color: #52525b;
        text-align: center;
        padding: 16px;
    }
    .log-entry {
        padding: 4px 8px;
        display: flex;
        gap: 8px;
    }
    .log-entry.error {
        background: rgba(239, 68, 68, 0.1);
        color: #ef4444;
    }
    .log-entry.info {
        color: #22c55e;
    }
    .log-entry.warn {
        color: #f97316;
    }
    .time { color: #52525b; }
    .type { font-weight: 600; }
    .msg { flex: 1; }
</style>