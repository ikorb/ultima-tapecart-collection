// Builds the editor into one self-contained HTML file that works offline
// from disk:  bun build.ts [out.html]   (default ../build/ultima-save-editor.html)
// Bun's bundler does the TypeScript; nothing is fetched from anywhere.

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";

declare const Bun: {
  build(o: { entrypoints: string[]; minify: boolean; target: string }): Promise<{
    success: boolean; logs: unknown[]; outputs: { text(): Promise<string> }[];
  }>;
};

const here = import.meta.dirname;
const out = process.argv[2] ?? join(here, "..", "build", "ultima-save-editor.html");
const result = await Bun.build({ entrypoints: [join(here, "src", "main.ts")], minify: true, target: "browser" });
if (!result.success) {
  for (const l of result.logs) process.stderr.write(`${l}\n`);
  process.exit(1);
}
const js = (await result.outputs[0].text()).replaceAll("</script", "<\\/script");
const css = readFileSync(join(here, "src", "ui", "style.css"), "utf8");
const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ultima Tapecart Collection save editor</title>
<style>${css}</style>
</head>
<body>
<div id="app"></div>
<noscript>The editor needs JavaScript.</noscript>
<script>${js}</script>
</body>
</html>
`;
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, html);
process.stdout.write(`${out}: ${html.length} bytes\n`);
