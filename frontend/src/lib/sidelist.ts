// The items of a SideList (components/SideList.svelte).

export interface SideItem {
  id: number;
  label: string;
  /** Where choosing it goes. */
  href: string;
  mono?: boolean;
  /** A second line: a note such as "No agreement", or what it is. */
  note?: string;
  noteTone?: "warning" | "muted";
  tags?: { tone: "info" | "neutral"; text: string }[];
  /** Under the item before it, as a virtual machine under its host. */
  indent?: boolean;
  /** Extra words the filter matches, such as an IP address or serial number. */
  keywords?: string;
}

export interface SideGroup {
  label: string;
  tone?: "ok" | "critical" | "neutral";
  items: SideItem[];
}
