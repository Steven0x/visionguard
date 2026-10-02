import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Button } from "./Button";
import { EmptyState } from "./EmptyState";
import { Modal } from "./Modal";
import { Tabs } from "./Tabs";

describe("Button", () => {
  it("defaults to type=button and fires onClick", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Go</Button>);
    const btn = screen.getByRole("button", { name: "Go" });
    expect(btn).toHaveAttribute("type", "button");
    fireEvent.click(btn);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("does not fire when disabled", () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Go
      </Button>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("Tabs", () => {
  function Harness() {
    const [v, setV] = useState("a");
    return (
      <Tabs
        tabs={[
          { key: "a", label: "A" },
          { key: "b", label: "B" },
        ]}
        value={v}
        onChange={setV}
      />
    );
  }

  it("marks the active tab and moves with ArrowRight", () => {
    render(<Harness />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tabs[0].parentElement!, { key: "ArrowRight" });
    expect(screen.getAllByRole("tab")[1]).toHaveAttribute("aria-selected", "true");
  });
});

describe("Modal", () => {
  it("renders when open and closes on Escape", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="Hi">
        body
      </Modal>,
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("renders nothing when closed", () => {
    render(
      <Modal open={false} onClose={() => {}}>
        body
      </Modal>,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("EmptyState", () => {
  it("shows title, description and an action", () => {
    render(
      <EmptyState title="Nothing here" description="yet" action={<Button>Add</Button>} />,
    );
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.getByText("yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add" })).toBeInTheDocument();
  });
});
