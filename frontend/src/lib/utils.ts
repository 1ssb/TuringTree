import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * cn — merge conditional class names and resolve Tailwind conflicts.
 *
 * clsx joins the truthy class names; tailwind-merge then makes sure that when
 * two conflicting Tailwind classes are present (e.g. px-4 and px-[29px]) the
 * LAST one wins. This is what lets callers override the Button's default
 * padding from a className prop.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
