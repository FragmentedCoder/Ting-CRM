<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { onMount } from "svelte";
  import { can, session } from "#lib/session.svelte.js";

  // The admin panel opens on the first section the user may see.
  onMount(() => {
    if (can(session.current, "administer")) goto(resolve("/(app)/admin/users"), { replace: true });
    else if (can(session.current, "read_audit_log")) {
      goto(resolve("/(app)/admin/audit"), { replace: true });
    } else if (can(session.current, "manage_customers")) {
      goto(resolve("/(app)/admin/general"), { replace: true });
    }
  });
</script>
