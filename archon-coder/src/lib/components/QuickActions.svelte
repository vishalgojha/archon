<script lang="ts">
    import { createEventDispatcher } from 'svelte';

    export let actions: string[] = [];

    const dispatch = createEventDispatcher();

    function handleAction(action: string) {
        dispatch('action', action);
    }
</script>

<div class="quick-actions">
    {#each actions as action}
        <button class="quick-btn" on:click={() => handleAction(action)}>
            {action}
        </button>
    {/each}
</div>

<style>
    .quick-actions {
        display: flex;
        gap: 8px;
        padding: 8px 20px;
        border-top: 1px solid #1E1E1E;
        background: #0A0A0A;
    }

    .quick-btn {
        background: #1E1E1E;
        border: 1px solid #1E1E1E;
        border-radius: 6px;
        padding: 6px 12px;
        font-size: 12px;
        color: #E8DCC8;
        cursor: pointer;
        transition: all 0.15s;
    }

    .quick-btn:hover {
        border-color: #E8DCC8;
        background: #252525;
    }
</style>