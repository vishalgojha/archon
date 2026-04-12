<script lang="ts">
    import { invoke } from '$lib/tauri-api';

    export let activeSessionId: string | null = null;

    let events: any[] = [];
    let narrative = '';

    async function load() {
        if (!activeSessionId) {
            events = [];
            narrative = '';
            return;
        }
        try {
            const raw = await invoke<string>('get_consciousness', { sessionId: activeSessionId });
            const data = JSON.parse(raw);
            events = data.events || [];
            narrative = data.narrative || '';
        } catch (e) {
            events = [];
            narrative = 'No events.';
        }
    }

    $: if (activeSessionId) load();

    const toneEmoji: Record<string, string> = {
        focused: '🎯', curious: '🔍', confident: '✓',
        uncertain: '?', excited: '⚡', reflective: '💭', neutral: '📋',
    };
    const toneColor: Record<string, string> = {
        focused: '#22c55e', curious: '#f97316', confident: '#22c55e',
        uncertain: '#a855f7', excited: '#f97316', reflective: '#a855f7', neutral: '#71717a',
    };
</script>

<aside class="panel">
    <div class="header">
        <h3>Consciousness</h3>
    </div>
    <div class="content">
        {#if events.length === 0}
            <div class="empty">No events yet. Send a command to begin.</div>
        {:else}
            {#each events as e}
                <div class="event">
                    <div class="event-head">
                        <span class="time">{e.time}</span>
                        <span class="emoji">{toneEmoji[e.tone] || '📋'}</span>
                        <span class="perspective" style="color: {toneColor[e.tone] || '#71717a'}">{e.perspective}</span>
                        <span class="type">{e.type}</span>
                    </div>
                    <div class="event-content">{e.content}</div>
                </div>
            {/each}
        {/if}
    </div>
</aside>

<style>
    .panel {
        width: 300px;
        background: #18181b;
        border-left: 1px solid #27272a;
        display: flex;
        flex-direction: column;
        flex-shrink: 0;
    }
    .header {
        padding: 12px 16px;
        border-bottom: 1px solid #27272a;
    }
    .header h3 { 
        font-size: 13px; 
        font-weight: 600; 
        color: #fafafa;
        margin: 0;
    }
    .content { 
        flex: 1; 
        overflow-y: auto; 
        padding: 12px; 
    }
    .empty { 
        text-align: center; 
        color: #52525b; 
        padding: 24px 12px; 
        font-size: 12px; 
    }
    .event {
        background: #09090b;
        border: 1px solid #27272a;
        border-radius: 8px;
        padding: 10px 12px;
        margin-bottom: 8px;
        animation: fadeIn 0.3s ease;
    }
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(4px); }
        to { opacity: 1; transform: translateY(0); }
    }
    .event-head {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 11px;
        margin-bottom: 6px;
    }
    .time { 
        color: #52525b; 
        font-family: monospace;
        font-size: 10px;
    }
    .emoji { font-size: 12px; }
    .perspective { 
        font-weight: 600; 
        font-family: monospace;
        font-size: 10px;
    }
    .type {
        margin-left: auto;
        background: #27272a;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 9px;
        color: #a1a1aa;
        text-transform: uppercase;
    }
    .event-content {
        font-size: 12px;
        color: #a1a1aa;
        line-height: 1.4;
        word-break: break-word;
    }
</style>