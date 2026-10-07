import { readFileSync } from "node:fs";

/** Expand shared adapter cases from one baseline and explicit field changes. */
export function providerFixtures(name: string): any[] {
  const { base, cases } = JSON.parse(
    readFileSync(new URL(`../conformance/v1/providers/${name}.json`, import.meta.url), "utf8"),
  );
  return cases.map((variant: any) => {
    const fixture = structuredClone(base);
    for (const path of variant.remove ?? []) {
      const parent = path
        .slice(0, -1)
        .reduce((node: any, key: string | number) => node[key], fixture);
      delete parent[path.at(-1)];
    }
    for (const [path, value] of variant.set) {
      const parent = path
        .slice(0, -1)
        .reduce((node: any, key: string | number) => node[key], fixture);
      Object.defineProperty(parent, path.at(-1), {
        value: structuredClone(value),
        enumerable: true,
        writable: true,
        configurable: true,
      });
    }
    return fixture;
  });
}
