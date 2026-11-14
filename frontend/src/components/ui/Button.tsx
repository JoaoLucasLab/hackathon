import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "text";

const variants: Record<Variant, string> = {
  // At most one primary button per screen (frontend.md).
  primary: "bg-ink text-surface font-semibold hover:bg-[#333] disabled:bg-[#9b978f]",
  secondary:
    "bg-surface text-ink font-medium border border-line hover:bg-field disabled:text-muted",
  text: "text-muted font-medium hover:text-ink disabled:opacity-60",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

export function Button({ variant = "secondary", className = "", type, ...rest }: ButtonProps) {
  const size = variant === "text" ? "min-h-11 px-1" : "min-h-11 px-4 rounded-btn";
  return (
    <button
      type={type ?? "button"}
      className={`inline-flex items-center justify-center gap-2 text-[15px] transition-colors duration-150 disabled:cursor-not-allowed ${size} ${variants[variant]} ${className}`}
      {...rest}
    />
  );
}
