import { createElement, type SVGProps } from "react";
import {
  Check,
  ChevronDown,
  ChevronLeft,
  CircleAlert,
  ExternalLink,
  FileX,
  Lock,
  Send,
  Star,
  Trash2,
  type LucideIcon,
} from "lucide-react";

// Lucide icons (lucide-react), same set and stroke as the Duo habit tracker.
const icons = {
  lock: Lock,
  send: Send,
  fileX: FileX,
  trash: Trash2,
  alert: CircleAlert,
  check: Check,
  star: Star,
  external: ExternalLink,
  chevronDown: ChevronDown,
  chevronLeft: ChevronLeft,
} satisfies Record<string, LucideIcon>;

export type IconName = keyof typeof icons;

export const ICON_STROKE = 2.25;

interface IconProps extends Omit<SVGProps<SVGSVGElement>, "name" | "ref"> {
  name: IconName;
  size?: number;
}

/** Decorative by default (`aria-hidden`). Color comes from `currentColor`. */
export function Icon({ name, size = 18, ...rest }: IconProps) {
  // createElement: the component comes from a lookup table, not defined per render.
  return createElement(icons[name], {
    size,
    strokeWidth: ICON_STROKE,
    "aria-hidden": true,
    focusable: false,
    ...rest,
  });
}

const TILE = {
  sm: { box: "size-8 rounded-lg", icon: 16 },
  md: { box: "size-10 rounded-xl", icon: 20 },
} as const;

interface IconTileProps {
  name: IconName;
  size?: keyof typeof TILE;
  /** A text color class; the tile is a 12% tint of the same color. */
  className?: string;
}

/** The icon on a soft tile tinted with its own color, as in the Duo habit tracker. */
export function IconTile({ name, size = "md", className = "" }: IconTileProps) {
  const t = TILE[size];
  return (
    <span
      aria-hidden="true"
      className={`relative flex shrink-0 items-center justify-center ${t.box} ${className}`}
    >
      <span className="absolute inset-0 rounded-[inherit] bg-current opacity-[0.12]" />
      <Icon name={name} size={t.icon} className="relative" />
    </span>
  );
}
