import { describe, expect, it } from "vitest";

import { agentKind, agentName, initials, kg, money, moneyWhole, slotColor } from "@/lib/format";

describe("money", () => {
  it("formats cents as Singapore dollars", () => {
    expect(money(123456)).toBe("S$1,234.56");
    expect(money(0)).toBe("S$0.00");
    expect(money(-950)).toBe("-S$9.50");
    expect(money(null)).toBe("-");
  });

  it("rounds headline figures to whole dollars", () => {
    expect(moneyWhole(233885)).toBe("S$2,339");
    expect(moneyWhole(49)).toBe("S$0");
  });

  it("shows food saved in kilograms", () => {
    expect(kg(8400)).toBe("8.4 kg");
  });
});

describe("agents", () => {
  const names = { "cafe-mei": "Café Mei", johorfarm: "Johor Farm Fresh" };

  it("names agents for people", () => {
    expect(agentName("shop:cafe-mei", names)).toBe("Café Mei");
    expect(agentName("owner:cafe-mei", names)).toBe("Café Mei (owner)");
    expect(agentName("supplier:johorfarm", names)).toBe("Johor Farm Fresh");
    expect(agentName("coordinator:swarm")).toBe("Swarm coordinator");
    expect(agentName("suppliers:all")).toBe("All suppliers");
    expect(agentName("shop:unknown-shop", names)).toBe("unknown-shop");
  });

  it("classifies agent ids", () => {
    expect(agentKind("shop:x")).toBe("shop");
    expect(agentKind("claims:swarm")).toBe("other");
  });

  it("makes two-letter initials, keeping ampersands", () => {
    expect(initials("Café Mei")).toBe("CM");
    expect(initials("Toast & Co")).toBe("T&");
    expect(initials("PackPro")).toBe("P");
  });

  it("gives each supplier a fixed colour slot, whatever its rank", () => {
    expect(slotColor("freshdairy")).toBe("var(--s1)");
    expect(slotColor("johorfarm")).toBe("var(--s2)");
    expect(slotColor("packpro")).toBe("var(--s3)");
  });
});
