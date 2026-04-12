<script lang="ts">
    import { createEventDispatcher } from 'svelte';

    export let contexts: string[] = [];

    const dispatch = createEventDispatcher();
</script>

<div class="section">
    <div class="section-header">
        <span class="section-title">CONTEXTS</span>
        <button class="add-btn" title="Add Context">+</button>
    </div>
    <div class="context-list">
        {#each contexts as context}
            <div 
                class="context-row" 
                role="button" 
                tabindex="0"
                on:click={() => dispatch('select', context)}
                on:keydown={(e) => e.key === 'Enter' && dispatch('select', context)}
            >
                <span class="context-prefix">#</span>
                <span class="context-name">{context}</span>
            </div>
        {/each}
    </div>
</div>

<style>
    .section {
        margin-bottom: 24px;
    }

    .section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
    }

    .section-title {
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 1px;
        color: #E8DCC8;
        opacity: 0.7;
    }

    .add-btn {
        background: transparent;
        border: 1px solid #1E1E1E;
        color: #E8DCC8;
        width: 24px;
        height: 24px;
        border-radius: 4px;
        cursor: pointer;
        font-size: 14px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .add-btn:hover {
        border-color: #E8DCC8;
        background: #1E1E1E;
    }

    .context-list {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .context-row {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 8px 10px;
        border-radius: 6px;
        cursor: pointer;
        transition: background 0.15s;
    }

    .context-row:hover {
        background: #1E1E1E;
    }

    .context-prefix {
        color: #E8DCC8;
        opacity: 0.5;
        font-size: 13px;
    }

    .context-name {
        font-size: 13px;
        color: #E8DCC8;
    }
</style>