/**
 * Unit tests for ``UserIdentityBlock`` (gap-cycle-03-011).
 *
 * Acceptance criteria covered:
 *
 * 1. Renders avatar ``<img>`` when ``avatarUrl`` is provided.
 * 2. Renders fallback icon when ``avatarUrl`` is null.
 * 3. Renders display name when ``displayName`` is set.
 * 4. Hides display name when ``displayName`` is null.
 * 5. ``?v=<cacheBust>`` appended to avatar src when provided.
 * 6. No cache-bust suffix when ``cacheBust`` is empty/omitted.
 */
import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import UserIdentityBlock from "../UserIdentityBlock.svelte";

describe("UserIdentityBlock — avatar rendering", () => {
  it("renders img when avatarUrl is set", () => {
    const { getByTestId } = render(UserIdentityBlock, {
      props: {
        displayName: "Alice",
        avatarUrl: "/api/preferences/avatar",
        cacheBust: "",
      },
    });
    const img = getByTestId("user-identity-avatar-img") as HTMLImageElement;
    expect(img.src).toContain("/api/preferences/avatar");
  });

  it("appends ?v=cacheBust to avatar src", () => {
    const { getByTestId } = render(UserIdentityBlock, {
      props: {
        displayName: "Alice",
        avatarUrl: "/api/preferences/avatar",
        cacheBust: "2026-01-01T00:00:00Z",
      },
    });
    const img = getByTestId("user-identity-avatar-img") as HTMLImageElement;
    expect(img.src).toContain("?v=");
    expect(img.src).toContain("2026-01-01");
  });

  it("renders fallback icon when avatarUrl is null", () => {
    const { getByTestId, queryByTestId } = render(UserIdentityBlock, {
      props: { displayName: null, avatarUrl: null },
    });
    expect(getByTestId("user-identity-avatar-fallback")).toBeTruthy();
    expect(queryByTestId("user-identity-avatar-img")).toBeNull();
  });

  it("no cache-bust when cacheBust is empty", () => {
    const { getByTestId } = render(UserIdentityBlock, {
      props: {
        displayName: null,
        avatarUrl: "/api/preferences/avatar",
        cacheBust: "",
      },
    });
    const img = getByTestId("user-identity-avatar-img") as HTMLImageElement;
    expect(img.src).not.toContain("?v=");
  });
});

describe("UserIdentityBlock — display name", () => {
  it("renders name when displayName is set", () => {
    const { getByTestId } = render(UserIdentityBlock, {
      props: { displayName: "Bob", avatarUrl: null },
    });
    expect(getByTestId("user-identity-name").textContent?.trim()).toBe("Bob");
  });

  it("hides name slot when displayName is null", () => {
    const { queryByTestId } = render(UserIdentityBlock, {
      props: { displayName: null, avatarUrl: null },
    });
    expect(queryByTestId("user-identity-name")).toBeNull();
  });
});
