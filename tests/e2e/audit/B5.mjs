import { open, done, close, check, report, shot, scrollTo, WIDTHS } from './lib.mjs';

const WIDTHS_WITH_PHONE = [320, 400, 768, 1440];
const SCENES = ['live', 'final'];

async function testNotches() {
  for (const w of WIDTHS_WITH_PHONE) {
    for (const scene of SCENES) {
      const p = await open(`/?sample=1&scene=${scene}`, w);

      // Scroll to tickets and wait for slide-in animation
      await scrollTo(p, '[data-testid=grid]', 1600);

      // Get first three tickets
      const tickets = await p.$$('.ticket');
      const ticketCount = Math.min(3, tickets.length);

      for (let i = 0; i < ticketCount; i++) {
        const ticket = tickets[i];
        const stub = await ticket.$('.stub');

        if (!stub) {
          check(`${w}px ${scene} ticket ${i+1}: stub found`, false, 'stub not found');
          continue;
        }

        // Get the ticket and stub rectangles
        const ticketRect = await ticket.boundingBox();
        const stubRect = await stub.boundingBox();

        // Check that ::before and ::after have content
        const beforeContent = await p.evaluate(
          el => getComputedStyle(el, '::before').content,
          stub
        );
        const afterContent = await p.evaluate(
          el => getComputedStyle(el, '::after').content,
          stub
        );

        check(`${w}px ${scene} ticket ${i+1}: ::before has content`, beforeContent !== 'none', `content="${beforeContent}"`);
        check(`${w}px ${scene} ticket ${i+1}: ::after has content`, afterContent !== 'none', `content="${afterContent}"`);

        if (w <= 560) {
          // Phone layout: notches are on left and right edges at the bottom
          const beforeCS = await p.evaluate(
            el => {
              const cs = getComputedStyle(el, '::before');
              return {
                width: parseFloat(cs.width) || 0,
                height: parseFloat(cs.height) || 0,
                left: parseFloat(cs.left) || 0,
                right: parseFloat(cs.right) || 0,
                top: parseFloat(cs.top) || 0,
                bottom: parseFloat(cs.bottom) || 0
              };
            },
            stub
          );

          const afterCS = await p.evaluate(
            el => {
              const cs = getComputedStyle(el, '::after');
              return {
                width: parseFloat(cs.width) || 0,
                height: parseFloat(cs.height) || 0,
                left: parseFloat(cs.left) || 0,
                right: parseFloat(cs.right) || 0,
                top: parseFloat(cs.top) || 0,
                bottom: parseFloat(cs.bottom) || 0
              };
            },
            stub
          );

          // Phone: ::before at left edge (uses left), ::after at right edge (uses right)
          const beforeCx = stubRect.x + beforeCS.left + beforeCS.width / 2;
          const afterCx = stubRect.x + stubRect.width - afterCS.right - afterCS.width / 2;

          check(
            `${w}px ${scene} ticket ${i+1}: ::before x at left edge`,
            Math.abs(beforeCx - ticketRect.x) <= 1,
            `cx=${beforeCx.toFixed(1)}, ticketX=${ticketRect.x.toFixed(1)}`
          );

          check(
            `${w}px ${scene} ticket ${i+1}: ::after x at right edge`,
            Math.abs(afterCx - (ticketRect.x + ticketRect.width)) <= 1,
            `cx=${afterCx.toFixed(1)}, ticketR=${(ticketRect.x + ticketRect.width).toFixed(1)}`
          );

          // Both center y should be within 1px of stubRect.bottom - 1 (uses bottom positioning)
          const beforeCy = stubRect.y + stubRect.height - beforeCS.bottom - beforeCS.height / 2;
          const afterCy = stubRect.y + stubRect.height - afterCS.bottom - afterCS.height / 2;
          const stubBottomCenter = stubRect.y + stubRect.height - 1;

          check(
            `${w}px ${scene} ticket ${i+1}: ::before y at stub bottom`,
            Math.abs(beforeCy - stubBottomCenter) <= 1,
            `cy=${beforeCy.toFixed(1)}, stubBottom-1=${stubBottomCenter.toFixed(1)}`
          );

          check(
            `${w}px ${scene} ticket ${i+1}: ::after y at stub bottom`,
            Math.abs(afterCy - stubBottomCenter) <= 1,
            `cy=${afterCy.toFixed(1)}, stubBottom-1=${stubBottomCenter.toFixed(1)}`
          );
        } else {
          // Desktop layout: notches are on right edge at top and bottom
          const beforeCS = await p.evaluate(
            el => {
              const cs = getComputedStyle(el, '::before');
              return {
                width: parseFloat(cs.width) || 0,
                height: parseFloat(cs.height) || 0,
                left: parseFloat(cs.left) || 0,
                right: parseFloat(cs.right) || 0,
                top: parseFloat(cs.top) || 0,
                bottom: parseFloat(cs.bottom) || 0
              };
            },
            stub
          );

          const afterCS = await p.evaluate(
            el => {
              const cs = getComputedStyle(el, '::after');
              return {
                width: parseFloat(cs.width) || 0,
                height: parseFloat(cs.height) || 0,
                left: parseFloat(cs.left) || 0,
                right: parseFloat(cs.right) || 0,
                top: parseFloat(cs.top) || 0,
                bottom: parseFloat(cs.bottom) || 0
              };
            },
            stub
          );

          // Desktop: both on right side, centered at x = stubRect.right - 1
          const beforeCx = stubRect.x + stubRect.width - beforeCS.right - beforeCS.width / 2;
          const afterCx = stubRect.x + stubRect.width - afterCS.right - afterCS.width / 2;
          const stubRightCenter = stubRect.x + stubRect.width - 1;

          check(
            `${w}px ${scene} ticket ${i+1}: ::before x centered on perforation`,
            Math.abs(beforeCx - stubRightCenter) <= 1,
            `cx=${beforeCx.toFixed(1)}, stubR-1=${stubRightCenter.toFixed(1)}`
          );

          check(
            `${w}px ${scene} ticket ${i+1}: ::after x centered on perforation`,
            Math.abs(afterCx - stubRightCenter) <= 1,
            `cx=${afterCx.toFixed(1)}, stubR-1=${stubRightCenter.toFixed(1)}`
          );

          // Top notch center y should be within 1px of ticketRect.top
          const beforeCy = stubRect.y + beforeCS.top + beforeCS.height / 2;
          check(
            `${w}px ${scene} ticket ${i+1}: ::before y at ticket top`,
            Math.abs(beforeCy - ticketRect.y) <= 1,
            `cy=${beforeCy.toFixed(1)}, ticketT=${ticketRect.y.toFixed(1)}`
          );

          // Bottom notch center y should be within 1px of ticketRect.bottom
          const afterCy = stubRect.y + stubRect.height - afterCS.bottom - afterCS.height / 2;
          const ticketBottom = ticketRect.y + ticketRect.height;
          check(
            `${w}px ${scene} ticket ${i+1}: ::after y at ticket bottom`,
            Math.abs(afterCy - ticketBottom) <= 1,
            `cy=${afterCy.toFixed(1)}, ticketB=${ticketBottom.toFixed(1)}`
          );
        }
      }

      check(`${w}px ${scene}: no console errors`, p.errors.length === 0, p.errors.join(' | '));
      await done(p);
    }
  }

  // Check for horizontal scroll at 320px
  {
    const p = await open('/?sample=1&scene=live', 320);
    await scrollTo(p, '[data-testid=grid]', 1600);
    const scrollWidth = await p.evaluate(() => document.documentElement.scrollWidth);
    const innerWidth = await p.evaluate(() => window.innerWidth);
    check('320px: no horizontal scroll', scrollWidth <= innerWidth, `scrollWidth=${scrollWidth}, innerWidth=${innerWidth}`);
    await done(p);
  }

  // Check that mini-ticket on model page doesn't have notch pseudo-elements
  for (const w of [400, 1440]) {
    const p = await open('/model?sample=1', w);
    const miniStub = await p.$('.mini-ticket .stub');
    if (miniStub) {
      const beforeContent = await p.evaluate(
        el => getComputedStyle(el, '::before').content,
        miniStub
      );
      check(
        `${w}px /model: mini-ticket .stub::before has no notch`,
        beforeContent === 'none',
        `content="${beforeContent}"`
      );
    }
    await done(p);
  }
}

await testNotches();
await close();
report();
