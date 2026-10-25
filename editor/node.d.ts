// The little of Node's API the tests, the CLI and the build use -- declared
// here so that type checking needs no @types/node (no npm install).

declare module "node:fs" {
  export function readFileSync(path: string): Uint8Array;
  export function readFileSync(path: string, encoding: "utf8"): string;
  export function writeFileSync(path: string, data: Uint8Array | string): void;
  export function existsSync(path: string): boolean;
  export function mkdirSync(path: string, opts?: { recursive?: boolean }): void;
  export function readdirSync(path: string): string[];
  export function rmSync(path: string, opts?: { recursive?: boolean; force?: boolean }): void;
}

declare module "node:path" {
  export function join(...parts: string[]): string;
  export function dirname(p: string): string;
  export function basename(p: string): string;
}

declare module "node:test" {
  type Fn = (t: { skip(msg?: string): void }) => void | Promise<void>;
  export function test(name: string, fn: Fn): void;
  export function test(name: string, opts: { skip?: boolean | string }, fn: Fn): void;
  export function describe(name: string, fn: () => void): void;
}

declare module "node:assert/strict" {
  interface Assert {
    (value: unknown, message?: string): asserts value;
    equal(a: unknown, b: unknown, message?: string): void;
    notEqual(a: unknown, b: unknown, message?: string): void;
    deepEqual(a: unknown, b: unknown, message?: string): void;
    ok(value: unknown, message?: string): asserts value;
    throws(fn: () => unknown, expected?: RegExp | object, message?: string): void;
    match(s: string, re: RegExp, message?: string): void;
  }
  const assert: Assert;
  export default assert;
}

declare module "node:child_process" {
  interface Child { kill(sig?: string): void; pid: number }
  export function spawn(cmd: string, args: string[], opts?: { stdio?: string }): Child;
}

declare module "node:os" {
  export function tmpdir(): string;
}

declare const process: {
  argv: string[];
  exit(code?: number): never;
  stdout: { write(s: string): void };
  stderr: { write(s: string): void };
};

interface ImportMeta { dirname: string; filename: string }
