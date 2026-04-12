<script lang="ts">
    import { createEventDispatcher } from 'svelte';

    export let agents: { name: string; color: string; initials: string }[] = [];

    const dispatch = createEventDispatcher();
</script>

<div class="section">
    <div class="section-header">
        <span class="section-title">AGENTS</span>
        <button class="add-btn" title="Add Agent">+</button>
    </div>
    <div class="agent-list">
        {#each agents as agent}
            <div 
                class="agent-row" 
                role="button" 
                tabindex="0"
                on:click={() => dispatch('select', agent)}
                on:keydown={(e) => e.key === 'Enter' && dispatch('select', agent)}
            >
                <span class="avatar" style="background: {agent.color}">{agent.initials}</span>
                <span class="agent-name">{agent.name}</span>
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

    .agent-list {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .agent-row {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 10px;
        border-radius: 6px;
        cursor: pointer;
        transition: background 0.15s;
    }

    .agent-row:hover {
        background: #1E1E1E;
    }

    .avatar {
        width: 28px;
        height: 28px;
        border-radius: 6px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 10px;
        font-weight: 600;
        color: #0A0A0A;
    }

    .agent-name {
        font-size: 13px;
        color: #E8DCC8;
    }
</style>