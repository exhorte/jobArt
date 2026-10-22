import { describe, expect, it } from "vitest";

import { decideAccess, expectedCredentials, parseBasicAuth } from "@/lib/basic-auth";

const basic = (user: string, password: string) =>
  `Basic ${Buffer.from(`${user}:${password}`, "utf8").toString("base64")}`;

const CONFIGURED = { BASIC_AUTH_USER: "moi", BASIC_AUTH_PASSWORD: "s3cret:avec-deux-points é" };

describe("configuration", () => {
  it("n'est active que si l'utilisateur et le mot de passe sont tous deux définis", () => {
    expect(expectedCredentials({})).toBeNull();
    expect(expectedCredentials({ BASIC_AUTH_USER: "moi" })).toBeNull();
    expect(expectedCredentials({ BASIC_AUTH_PASSWORD: "x" })).toBeNull();
    expect(expectedCredentials({ BASIC_AUTH_USER: " ", BASIC_AUTH_PASSWORD: "x" })).toBeNull();
    expect(expectedCredentials(CONFIGURED)).toEqual({ user: "moi", password: "s3cret:avec-deux-points é" });
  });

  it("reste ouverte en local, mais se verrouille sur Vercel ou avec REQUIRE_AUTH=1", () => {
    expect(decideAccess(null, {})).toBe("allow");
    expect(decideAccess(null, { VERCEL: "1" })).toBe("misconfigured");
    expect(decideAccess(null, { REQUIRE_AUTH: "1" })).toBe("misconfigured");
    expect(decideAccess(null, { REQUIRE_AUTH: "0" })).toBe("allow");
  });
});

describe("en-tête Authorization", () => {
  it("décode l'UTF-8 et coupe au premier deux-points", () => {
    expect(parseBasicAuth(basic("moi", "a:b é"))).toEqual({ user: "moi", password: "a:b é" });
    expect(parseBasicAuth(basic("moi", "a:b é").replace("Basic", "basic"))).toEqual({ user: "moi", password: "a:b é" });
  });

  it("ignore tout ce qui n'est pas du Basic lisible", () => {
    expect(parseBasicAuth(null)).toBeNull();
    expect(parseBasicAuth("")).toBeNull();
    expect(parseBasicAuth("Bearer abc")).toBeNull();
    expect(parseBasicAuth("Basic")).toBeNull();
    expect(parseBasicAuth("Basic !!!")).toBeNull();
    expect(parseBasicAuth(`Basic ${Buffer.from("sans-separateur").toString("base64")}`)).toBeNull();
  });
});

describe("décision d'accès", () => {
  it("laisse passer les bons identifiants", () => {
    expect(decideAccess(basic("moi", "s3cret:avec-deux-points é"), CONFIGURED)).toBe("allow");
  });

  it("demande une authentification sinon", () => {
    expect(decideAccess(null, CONFIGURED)).toBe("challenge");
    expect(decideAccess(basic("moi", "mauvais"), CONFIGURED)).toBe("challenge");
    expect(decideAccess(basic("autre", "s3cret:avec-deux-points é"), CONFIGURED)).toBe("challenge");
    expect(decideAccess(basic("", ""), CONFIGURED)).toBe("challenge");
    expect(decideAccess("Basic %%%", CONFIGURED)).toBe("challenge");
  });

  it("refuse un mot de passe qui n'est qu'un préfixe du bon", () => {
    expect(decideAccess(basic("moi", "s3cret"), CONFIGURED)).toBe("challenge");
  });
});
