<script lang="ts">
  // The standing-stones mark from docs/brand: nine stones in a ring, or the
  // favicon's seven heavier ones at 32 px and below. In dark mode it gets the white
  // inner frame (ting-mark-framed.svg) so the tile edge reads against dark surfaces.
  let { size = 48 }: { size?: number } = $props();

  // x, y, width, height of each stone, back to front, as in docs/brand.
  const NINE = [
    [56.3, 39.1, 13.2, 22.5], [90.5, 39.1, 13.2, 22.5],
    [116.1, 47.0, 14.5, 26.0], [29.4, 47.0, 14.5, 26.0],
    [121.0, 59.1, 16.5, 31.4], [22.5, 59.1, 16.5, 31.4],
    [103.0, 69.8, 18.3, 36.1], [38.7, 69.8, 18.3, 36.1],
    [70.5, 74.0, 19.0, 38.0],
  ];
  const SEVEN = [
    [49.5, 33.7, 19.3, 28.9], [91.2, 33.7, 19.3, 28.9],
    [22.3, 45.2, 21.7, 35.0], [115.9, 45.2, 21.7, 35.0],
    [105.2, 59.6, 24.7, 42.6], [30.1, 59.6, 24.7, 42.6],
    [67.0, 66.0, 26.0, 46.0],
  ];
  const stones = $derived(size <= 32 ? SEVEN : NINE);
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
  <rect class="frame" x="6" y="6" width="148" height="148" rx="31" fill="none" stroke-width="3" />
  <g fill="#9A78B0" stroke="#0F1B2D" stroke-width="3" stroke-linejoin="round">
    {#each stones as [x, y, width, height], i (i)}
      <rect {x} {y} {width} {height} rx="5" />
    {/each}
  </g>
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
