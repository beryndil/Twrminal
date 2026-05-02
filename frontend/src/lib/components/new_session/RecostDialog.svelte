<script lang="ts">
  /**
   * Quota-downgrade banner with "Use <model> anyway" override.
   *
   * Spec §4 + §6 + §8 — when ``apply_quota_guard`` downgrades the
   * routed executor (Opus → Sonnet at overall ≥ 80 %, Sonnet →
   * Haiku at sonnet ≥ 80 %), the new-session dialog renders a
   * yellow banner above the Start button:
   *
   *   "Routing downgraded to Sonnet (overall quota at NN%).
   *    [Use Opus anyway]"
   *
   * Clicking the override fires :prop:`onUseAnyway` which the
   * parent uses to (a) restore the original executor on the
   * selectors and (b) record the override as
   * ``manual_override_quota`` for analytics (spec §4).
   *
   * The "Recost" filename matches the master-checklist contract
   * ("RecostDialog.svelte — probably part of the 'Use anyway'
   * flow"); spec §7's mid-session recost dialog ("Switch executor:
   * Sonnet → Opus / This will re-cost ~38,000 input tokens …") is a
   * separate item (2.x mid-session controls). This file is the
   * v1.0 quota-downgrade banner; the §7 mid-session variant lands
   * later.
   */
  import { NEW_SESSION_STRINGS } from "../../config";

  /**
   * Inputs the parent feeds the banner. ``downgradedTo`` is the
   * post-guard executor (the model the session WOULD start with);
   * ``originalModel`` is what the rule had picked pre-guard (what
   * the "Use anyway" button restores). ``bucket`` selects the copy
   * suffix (overall vs sonnet quota); ``usedPct`` is the snapshot
   * percentage so the banner can render ``"(overall quota at
   * 81%)"``.
   */
  interface Props {
    downgradedTo: string;
    originalModel: string;
    bucket: "overall" | "sonnet";
    usedPct: number;
    onUseAnyway: () => void;
  }

  const { downgradedTo, originalModel, bucket, usedPct, onUseAnyway }: Props = $props();

  function capitalize(model: string): string {
    if (model.length === 0) return model;
    return model.charAt(0).toUpperCase() + model.slice(1);
  }

  const pctText = $derived(`${Math.round(usedPct * 100)}`);
  const suffixTemplate = $derived(
    bucket === "overall"
      ? NEW_SESSION_STRINGS.downgradeBannerOverallSuffixTemplate
      : NEW_SESSION_STRINGS.downgradeBannerSonnetSuffixTemplate,
  );
  const bannerSuffix = $derived(suffixTemplate.replace("{pct}", pctText));
  // Composed into one string so the rendered ``textContent`` is a
  // single line (Prettier otherwise splits each ``{...}`` interpolation
  // onto its own line, which leaks newlines into ``textContent`` and
  // — more importantly — produces a visibly multi-line banner in the
  // browser whenever the surrounding container is narrower than the
  // copy. The spec §6 wording reads as one sentence.
  const bannerText = $derived(
    `${NEW_SESSION_STRINGS.downgradeBannerPrefix} ${capitalize(downgradedTo)} ${bannerSuffix}`,
  );
  const buttonLabel = $derived(
    NEW_SESSION_STRINGS.downgradeUseAnywayLabel.replace("{model}", capitalize(originalModel)),
  );
</script>

<div class="recost-dialog" role="alert" data-testid="recost-dialog" data-bucket={bucket}>
  <p class="recost-dialog__copy" data-testid="recost-dialog-copy">{bannerText}</p>
  <button
    type="button"
    class="recost-dialog__override"
    data-testid="recost-dialog-use-anyway"
    onclick={onUseAnyway}
  >
    {buttonLabel}
  </button>
</div>

<style>
  .recost-dialog {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
    padding: 0.5rem 0.75rem;
    background: rgba(250, 204, 21, 0.12);
    border: 1px solid #facc15;
    border-radius: 0.375rem;
    font-size: 0.8125rem;
  }
  .recost-dialog__copy {
    margin: 0;
    color: rgb(var(--bearings-fg));
    flex: 1 1 auto;
  }
  .recost-dialog__override {
    background: transparent;
    border: 1px solid currentColor;
    border-radius: 0.25rem;
    padding: 0.25rem 0.5rem;
    color: #facc15;
    cursor: pointer;
    font: inherit;
  }
  .recost-dialog__override:hover,
  .recost-dialog__override:focus-visible {
    background: #facc15;
    color: rgb(var(--bearings-surface-0));
  }
</style>
