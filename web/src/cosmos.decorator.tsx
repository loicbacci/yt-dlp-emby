import type { ComponentChildren } from "preact";

export default function CosmosDecorator({
  children,
}: {
  children: ComponentChildren;
}) {
  return <div class="mock-root">{children}</div>;
}
