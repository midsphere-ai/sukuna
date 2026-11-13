import { writable } from 'svelte/store';

/**
 * Store for pre-filling the chat input box.
 * Used by follow-up question chips to auto-fill text into the input.
 * The chat input component (US-044) will subscribe to this store.
 */
export const chatInputPrefill = writable<string>('');

/**
 * When true, the chat input will auto-submit after receiving a prefill value.
 * Used by edit-and-resubmit flow to branch + auto-send the edited message.
 */
export const chatInputAutoSubmit = writable<boolean>(false);
