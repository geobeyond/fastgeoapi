/**
 * Controls that say what they do.
 *
 * rjsf's plain theme draws add and remove as bootstrap glyphs, and this
 * page loads no bootstrap — so both arrive as empty boxes carrying a
 * `title` and no text. Adding and removing a collection is most of what
 * an operator comes here to do; those cannot be shapes you have to hover
 * over to identify.
 *
 * Only the buttons are replaced. Everything else rjsf renders is left
 * alone: the less of its layout we own, the less of it we have to keep
 * working across versions.
 */

import type { IconButtonProps, TemplatesType } from "@rjsf/utils";

import { Button } from "@/components/ui/button";

function Labelled({
  label,
  variant,
  ...props
}: IconButtonProps & { label: string; variant?: "outline" | "destructive" }) {
  const {
    icon: _icon,
    iconType: _iconType,
    uiSchema: _uiSchema,
    registry: _registry,
    ...button
  } = props;
  return (
    <Button
      type="button"
      size="control"
      variant={variant ?? "outline"}
      {...button}
    >
      {label}
    </Button>
  );
}

/**
 * The add button.
 *
 * rjsf uses the same one for a list and for a free mapping — which is
 * how a collection gets added, `resources` being a mapping whose keys
 * are names — so the word has to make sense for both.
 */
function AddButton(props: IconButtonProps) {
  return <Labelled {...props} label="Add" />;
}

function RemoveButton(props: IconButtonProps) {
  return <Labelled {...props} label="Remove" variant="destructive" />;
}

function MoveUpButton(props: IconButtonProps) {
  return <Labelled {...props} label="Move up" />;
}

function MoveDownButton(props: IconButtonProps) {
  return <Labelled {...props} label="Move down" />;
}

function CopyButton(props: IconButtonProps) {
  return <Labelled {...props} label="Duplicate" />;
}

export const templates: Partial<TemplatesType> = {
  ButtonTemplates: {
    AddButton,
    RemoveButton,
    MoveUpButton,
    MoveDownButton,
    CopyButton,
  } as TemplatesType["ButtonTemplates"],
};
