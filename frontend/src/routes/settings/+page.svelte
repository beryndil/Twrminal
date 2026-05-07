<script lang="ts">
  /**
   * Settings route — mounts ``SettingsShell`` with the full section registry.
   *
   * This file is intentionally thin: all layout, keyboard navigation,
   * URL deep-linking (``?settings=<id>``), and save-status aggregation live
   * in ``SettingsShell``. Section content lives in the individual section
   * components under ``$lib/components/settings/sections/``.
   *
   * To add a new settings section, append an entry to
   * ``$lib/components/settings/sections.ts`` — no changes to this file.
   *
   * Reachable via the ``/settings`` route. The center column of
   * ``+layout.svelte`` renders this page when no session is selected.
   */
  import SettingsShell from "$lib/components/settings/SettingsShell.svelte";
</script>

<SettingsShell />
