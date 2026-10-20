// Export the first SVG inside an element as a PNG download.
// CSS variables in SVG attributes don't resolve once the SVG is serialised on its own, so
// computed values are inlined first.

const VAR = /var\((--[a-z0-9-]+)\)/gi;

function resolveVars(value: string, root: CSSStyleDeclaration): string {
  return value.replace(VAR, (_, name: string) => root.getPropertyValue(name).trim() || "#888");
}

export async function exportChartPng(container: HTMLElement | null, filename: string): Promise<void> {
  const svg = container?.querySelector("svg");
  if (!svg) throw new Error("There is no chart to export.");
  const rootStyle = getComputedStyle(document.documentElement);
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const { width, height } = svg.getBoundingClientRect();
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  for (const el of [clone, ...Array.from(clone.querySelectorAll("*"))]) {
    for (const attr of ["fill", "stroke", "style", "color"]) {
      const v = el.getAttribute(attr);
      if (v && v.includes("var(")) el.setAttribute(attr, resolveVars(v, rootStyle));
    }
  }
  const data = new XMLSerializer().serializeToString(clone);
  const img = new Image();
  const url = URL.createObjectURL(new Blob([data], { type: "image/svg+xml;charset=utf-8" }));
  try {
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("Could not render the chart image."));
      img.src = url;
    });
    const scale = 2;
    const canvas = document.createElement("canvas");
    canvas.width = Math.ceil(width * scale);
    canvas.height = Math.ceil(height * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas is not available.");
    ctx.fillStyle = rootStyle.getPropertyValue("--paper").trim() || "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0, width, height);
    const a = document.createElement("a");
    a.download = filename;
    a.href = canvas.toDataURL("image/png");
    a.click();
  } finally {
    URL.revokeObjectURL(url);
  }
}
