import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge class names, letting later Tailwind utilities win over earlier ones.
 *
 * Plain `clsx` would leave both `p-2` and `p-4` in the output and let CSS source
 * order decide, which makes a component's `className` override unreliable.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
