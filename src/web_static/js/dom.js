// Tiny DOM helpers. Data only ever enters the page as text nodes, never as markup.

const SVG_NS = "http://www.w3.org/2000/svg";
const SPRITE = "/static/img/icons.svg";
const PROPERTIES = new Set(["value", "checked", "disabled", "hidden", "readOnly", "selected"]);

function append(parent, children) {
  for (const child of children) {
    if (child === null || child === undefined || child === false || child === "") continue;
    if (Array.isArray(child)) append(parent, child);
    else parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function h(tag, props, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") {
      element.className = value;
    } else if (key === "style") {
      for (const [name, item] of Object.entries(value)) element.style.setProperty(name, item);
    } else if (key.startsWith("on") && typeof value === "function") {
      element.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (PROPERTIES.has(key)) {
      element[key] = value;
    } else {
      element.setAttribute(key === "htmlFor" ? "for" : key, value === true ? "" : String(value));
    }
  }
  append(element, children);
  return element;
}

export function icon(name, { size, cls, label } = {}) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", cls ? `icon ${cls}` : "icon");
  if (label) {
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", label);
  } else {
    svg.setAttribute("aria-hidden", "true");
  }
  if (size) svg.style.setProperty("--icon", size);
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `${SPRITE}#i-${name}`);
  svg.append(use);
  return svg;
}

export function clear(node) {
  node.replaceChildren();
  return node;
}

/** Replaces the children of a node; null, undefined and false are skipped like in h(). */
export function setChildren(node, ...children) {
  node.replaceChildren();
  append(node, children);
  return node;
}

/** Writes text only when it changed, so one-second polls do not touch stable nodes. */
export function setText(node, value) {
  const text = String(value);
  if (node.textContent !== text) node.textContent = text;
}

export function setAttr(node, name, value) {
  if (value === null || value === undefined || value === false) {
    if (node.hasAttribute(name)) node.removeAttribute(name);
  } else {
    const text = value === true ? "" : String(value);
    if (node.getAttribute(name) !== text) node.setAttribute(name, text);
  }
}

/** A file name that truncates in the middle so the extension stays visible. */
export function fileName(name, tailLength = 12) {
  const text = String(name ?? "");
  const cut = text.length > tailLength * 2 ? text.length - tailLength : text.length;
  return h(
    "span",
    { class: "file", title: text },
    h("span", { class: "file-head" }, text.slice(0, cut)),
    cut < text.length && h("span", { class: "file-tail" }, text.slice(cut)),
  );
}

/**
 * A file system path that wraps only after its separators: a <wbr> follows every "/" and
 * "\", so a line never breaks inside a folder name unless that name alone exceeds the line.
 */
export function pathText(path, cls = "path mono") {
  const text = String(path ?? "");
  const element = h("span", { class: cls });
  let start = 0;
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] !== "/" && text[index] !== "\\") continue;
    element.append(text.slice(start, index + 1), h("wbr"));
    start = index + 1;
  }
  if (start < text.length) element.append(text.slice(start));
  return element;
}

export function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
