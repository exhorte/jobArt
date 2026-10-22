import { describe, expect, it } from "vitest";

import {
  DASH,
  formatDate,
  formatDuration,
  formatInterval,
  formatNumber,
  formatRelative,
  formatSalary,
  formatScore,
  label,
  safeExternalUrl,
  scoreTone,
} from "@/lib/format";

describe("valeurs absentes", () => {
  it("n'invente jamais de donnée : absent → tiret", () => {
    expect(formatDate(null)).toBe(DASH);
    expect(formatDate("pas une date")).toBe(DASH);
    expect(formatNumber(undefined)).toBe(DASH);
    expect(formatScore(null)).toBe(DASH);
    expect(formatDuration(null)).toBe(DASH);
    expect(formatRelative(undefined)).toBe(DASH);
    expect(label({ a: "A" }, null)).toBe(DASH);
  });

  it("garde la clé brute quand le libellé est inconnu", () => {
    expect(label({ cdi: "CDI" }, "cdi")).toBe("CDI");
    expect(label({ cdi: "CDI" }, "nouveau_contrat")).toBe("nouveau_contrat");
  });
});

describe("durées et intervalles", () => {
  it("formate les durées de collecte", () => {
    expect(formatDuration(450)).toBe("450 ms");
    expect(formatDuration(31_000)).toBe("31 s");
    expect(formatDuration(82_000)).toBe("1 min 22 s");
  });

  it("formate les intervalles de veille", () => {
    expect(formatInterval(30)).toBe("30 min");
    expect(formatInterval(360)).toBe("6 h");
    expect(formatInterval(1440)).toBe("24 h");
    expect(formatInterval(2880)).toBe("2 j");
    expect(formatInterval(90)).toBe("90 min");
  });
});

describe("temps relatif", () => {
  const now = Date.parse("2026-10-21T12:00:00Z");
  it("passé et futur", () => {
    expect(formatRelative("2026-10-21T10:00:00Z", now)).toContain("2");
    expect(formatRelative("2026-10-21T10:00:00Z", now)).toMatch(/il y a/);
    expect(formatRelative("2026-10-21T18:00:00Z", now)).toMatch(/dans/);
  });
  it("au-delà d'un mois : date absolue", () => {
    expect(formatRelative("2026-06-01T00:00:00Z", now)).toMatch(/2026/);
  });
});

describe("score", () => {
  it("arrondit et classe par seuils", () => {
    expect(formatScore(72.4)).toBe("72");
    expect(scoreTone(70)).toBe("success");
    expect(scoreTone(69.9)).toBe("warning");
    expect(scoreTone(50)).toBe("warning");
    expect(scoreTone(49)).toBe("neutral");
    expect(scoreTone(null)).toBe("neutral");
  });
});

describe("salaire", () => {
  const base = { salary_min: null, salary_max: null, salary_currency: null, salary_period: null };
  it("n'affiche rien sans donnée", () => {
    expect(formatSalary(base)).toBeNull();
  });
  it("affiche la fourchette déclarée", () => {
    const out = formatSalary({ ...base, salary_min: 500000, salary_max: 800000, salary_currency: "XOF", salary_period: "mois" });
    expect(out).toMatch(/500\D000 – 800\D000 XOF \/ mois/);
  });
});

describe("liens externes (URLs issues de sites tiers)", () => {
  it("accepte http et https", () => {
    expect(safeExternalUrl("https://exemple.org/offre/1")).toBe("https://exemple.org/offre/1");
    expect(safeExternalUrl("http://exemple.org/")).toBe("http://exemple.org/");
  });
  it("refuse les schémas dangereux et les valeurs invalides", () => {
    expect(safeExternalUrl("javascript:alert(1)")).toBeNull();
    expect(safeExternalUrl("data:text/html,<script>1</script>")).toBeNull();
    expect(safeExternalUrl("ftp://exemple.org/f")).toBeNull();
    expect(safeExternalUrl("//exemple.org")).toBeNull();
    expect(safeExternalUrl("")).toBeNull();
    expect(safeExternalUrl(null)).toBeNull();
  });
});
