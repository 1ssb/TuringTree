import "./StarBorder.css";
import type { CSSProperties, ElementType, ReactNode } from "react";

/**
 * StarBorder — React Bits component (JS + CSS variant), ported to TypeScript.
 *
 * Renders children inside a panel ringed by two animated radial-gradient
 * "stars" that sweep along the top and bottom edges. Polymorphic via `as`
 * (e.g. `as={Link}` for a react-router link, or the default `button`).
 *
 * Props: as, className, color (border color, fades to transparent), speed
 * (animation duration), thickness (border glow size). Any extra props (e.g.
 * `to`, `onClick`) are forwarded to the rendered element.
 */
interface StarBorderProps {
  as?: ElementType;
  className?: string;
  color?: string;
  speed?: string;
  thickness?: number;
  children?: ReactNode;
  style?: CSSProperties;
  [key: string]: unknown;
}

export default function StarBorder({
  as: Component = "button",
  className = "",
  color = "white",
  speed = "6s",
  thickness = 1,
  children,
  style,
  ...rest
}: StarBorderProps) {
  const Tag = Component as ElementType;

  return (
    <Tag
      className={`star-border-container ${className}`}
      style={{ padding: `${thickness}px 0`, ...style }}
      {...rest}
    >
      <div
        className="border-gradient-bottom"
        style={{
          background: `radial-gradient(circle, ${color}, transparent 10%)`,
          animationDuration: speed,
        }}
      />
      <div
        className="border-gradient-top"
        style={{
          background: `radial-gradient(circle, ${color}, transparent 10%)`,
          animationDuration: speed,
        }}
      />
      <div className="inner-content">{children}</div>
    </Tag>
  );
}
