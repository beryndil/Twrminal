/**
 * Settings section registry — gap-cycle-07-007.
 *
 * ``SETTINGS_SECTIONS`` is the single source of truth for section ordering
 * and component mapping. To add a new section: append one entry here.
 * ``SettingsShell`` and ``+page.svelte`` do not enumerate sections inline.
 */
import type { Component } from "svelte";

import AboutSection from "./sections/AboutSection.svelte";
import AppearanceSection from "./sections/AppearanceSection.svelte";
import AuthSection from "./sections/AuthSection.svelte";
import DefaultsSection from "./sections/DefaultsSection.svelte";
import HelpSection from "./sections/HelpSection.svelte";
import ImportSection from "./sections/ImportSection.svelte";
import NotificationsSection from "./sections/NotificationsSection.svelte";
import PrivacySection from "./sections/PrivacySection.svelte";
import ProfileSection from "./sections/ProfileSection.svelte";
import RoutingRulesSection from "./sections/RoutingRulesSection.svelte";

/** Save-status emitted by section components that persist data. */
export interface SaveStatus {
  state: "idle" | "saving" | "saved" | "error";
  message?: string;
}

/** Minimal prop surface that every section component honours. */
export interface SectionProps {
  onsaveStatus?: (status: SaveStatus) => void;
}

/** One entry in the settings section registry. */
export interface SettingsSectionDef {
  /** Stable URL-safe identifier; mirrors the ``?settings=<id>`` param. */
  id: string;
  /** Human-readable nav-rail label. */
  label: string;
  /** Sort weight — lower values appear higher in the rail. */
  weight: number;
  /** Svelte 5 component constructor accepting ``SectionProps``. */
  // Component<any> is intentional: each section has its own concrete props
  // that are a superset of SectionProps. The shell passes onsaveStatus only.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  component: Component<any>;
}

/**
 * Ordered registry of settings sections.
 *
 * Sorted by ``weight`` ascending — lower weight renders higher in the rail.
 * Append a new entry here to add a section; no other file needs changing.
 */
export const SETTINGS_SECTIONS: readonly SettingsSectionDef[] = [
  { id: "profile", label: "Profile", weight: 10, component: ProfileSection },
  { id: "appearance", label: "Appearance", weight: 20, component: AppearanceSection },
  { id: "defaults", label: "Defaults", weight: 30, component: DefaultsSection },
  { id: "notifications", label: "Notifications", weight: 40, component: NotificationsSection },
  { id: "authentication", label: "Authentication", weight: 50, component: AuthSection },
  { id: "privacy", label: "Privacy", weight: 60, component: PrivacySection },
  { id: "routing", label: "System routing", weight: 70, component: RoutingRulesSection },
  { id: "import", label: "Data import", weight: 80, component: ImportSection },
  { id: "help", label: "Help", weight: 90, component: HelpSection },
  { id: "about", label: "About", weight: 100, component: AboutSection },
] as const;
