<script lang="ts">
  // The Ansuz mark from docs/brand. In dark mode it gets the white inner frame
  // (ting-mark-framed.svg) so the tile edge reads against dark surfaces.
  let { size = 48 }: { size?: number } = $props();
</script>

<svg
  class="mark"
  width={size}
  height={size}
  viewBox="0 0 160 160"
  aria-hidden="true"
  focusable="false"
>
  <rect width="160" height="160" rx="36" fill="#0F1B2D" />
  <rect class="frame" x="4" y="4" width="152" height="152" rx="33" fill="none" stroke-width="4" />
  <path
    d="M62 36 V124 M62 40 L98 64 M62 64 L98 88"
    fill="none"
    stroke="#C8862A"
    stroke-width={size <= 32 ? 18 : 12}
    stroke-linecap="round"
    stroke-linejoin="round"
  />
</svg>

<style>
  .mark {
    flex: none;
  }
  .frame {
    stroke: transparent;
  }
  @media (prefers-color-scheme: dark) {
    :global(:root:not([data-theme="light"])) .frame {
      stroke: #ffffff;
    }
  }
  :global(:root[data-theme="dark"]) .frame {
    stroke: #ffffff;
  }
</style>
