// Per-route prerendered HTML so each page's `<head>` carries the correct
// `<link rel="stylesheet">` and modulepreload tags. SSR is required at
// build time for SvelteKit to trace which CSS belongs to which route;
// `onMount` and other browser-only hooks still run client-side only.
export const prerender = true;
