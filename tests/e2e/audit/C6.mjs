// C6: Rank bump chart - no overlaps, phones keep ranks/names/values
import { open, done, close, check, report, shot, scrollTo, intersects } from './lib.mjs';

const WIDTHS = [320, 400, 560, 768, 1440];

for (const w of WIDTHS) {
  const p = await open('/model?sample=1', w);

  // Scroll to the bump chart and wait for animations
  await scrollTo(p, '#ch5 [data-bump]', 2200);

  // 1. No console errors
  check(`${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

  // 2. Get the SVG and measure text elements
  const svg = await p.$('#ch5 [data-bump] svg');
  if (svg) {
    // Collect all visible text elements with their metrics
    const data = await p.evaluate(() => {
      const svg = document.querySelector('#ch5 [data-bump] svg');
      const card = svg.closest('.card');
      if (!svg || !card) return null;

      const svgBox = svg.getBoundingClientRect();
      const cardBox = card.getBoundingClientRect();
      const scale = svgBox.width / svg.viewBox.baseVal.width;

      const texts = Array.from(svg.querySelectorAll('text')).filter(el => {
        const opacity = parseFloat(getComputedStyle(el).opacity || 1);
        return opacity > 0.05;
      }).map(el => {
        const cssFS = parseFloat(getComputedStyle(el).fontSize);
        const renderedFS = cssFS * scale;
        const box = el.getBoundingClientRect();
        return {
          text: el.textContent,
          cssFS,
          renderedFS,
          x: parseFloat(el.getAttribute('x')),
          y: parseFloat(el.getAttribute('y')),
          box: { left: box.left, top: box.top, right: box.right, bottom: box.bottom, width: box.width, height: box.height },
          classes: el.getAttribute('class')
        };
      });

      return { texts, scale, svgBox, cardBox };
    });

    if (data) {
      const { texts, scale, svgBox, cardBox } = data;

      // 3. Check rendered font sizes >= 11px
      texts.forEach((t, i) => {
        check(`${w}: text[${i}] rendered font >= 11px`, t.renderedFS >= 10.99, `${t.renderedFS.toFixed(2)}px`);
      });

      // 4. Check no overlaps with tolerance
      for (let i = 0; i < texts.length; i++) {
        for (let j = i + 1; j < texts.length; j++) {
          const overlaps = intersects(texts[i].box, texts[j].box, 1);
          check(
            `${w}: text[${i}] vs text[${j}] no overlap`,
            !overlaps,
            overlaps ? `"${texts[i].text}" vs "${texts[j].text}"` : 'clear'
          );
        }
      }

      // 5. Check containment in card (±0.5px tolerance)
      texts.forEach((t, i) => {
        const fits = t.box.left >= cardBox.left - 0.5 &&
                     t.box.right <= cardBox.right + 0.5 &&
                     t.box.top >= cardBox.top - 0.5 &&
                     t.box.bottom <= cardBox.bottom + 0.5;
        check(
          `${w}: text[${i}]("${t.text}") inside card`,
          fits,
          fits ? 'contained' : `x ${t.box.left.toFixed(0)}–${t.box.right.toFixed(0)} vs card ${cardBox.left.toFixed(0)}–${cardBox.right.toFixed(0)}`
        );
      });

      // 6. Check layout structure
      const rks = texts.filter(t => t.classes && t.classes.includes('rk')).length;
      const nms = texts.filter(t => t.classes && t.classes.includes('nm'));
      const vls = texts.filter(t => t.classes && t.classes.includes('vl')).length;

      const colXMax = texts.filter(t => t.classes && t.classes.includes('col'))
        .map(t => t.x).reduce((a, b) => Math.max(a, b), 0);

      if (w < 560) {
        check(`${w}: narrow has rank numbers`, rks === 6, `got ${rks}`);
        check(`${w}: narrow keeps right names`, nms.length >= 5, `got ${nms.length}`);
        const leftNms = nms.filter(n => n.x < colXMax / 2).length;
        check(`${w}: narrow no left names`, leftNms === 0, `got ${leftNms}`);
      } else {
        const isWide = nms.length === 12;
        const isNarrow = nms.length === 6 && rks === 6;
        if (isWide) {
          check(`${w}: wide has 6 ranks`, rks === 6, `got ${rks}`);
          check(`${w}: wide has 12 names`, nms.length === 12, `got ${nms.length}`);
          const colsubs = texts.filter(t => t.classes && t.classes.includes('colsub'));
          colsubs.forEach((cs, i) => {
            check(`${w}: colsub[${i}] y≈14`, Math.abs(cs.y - 14) <= 2, `${cs.y}`);
          });
        } else if (isNarrow) {
          check(`${w}: narrow 6 ranks`, rks === 6, `got ${rks}`);
          check(`${w}: narrow 6 right names`, nms.length === 6, `got ${nms.length}`);
        }
      }
    }
  }

  // Take after-screenshot
  await shot(p, `C6-${w}`, '#ch5 [data-bump]');
  await done(p);
}

await close();
report();
