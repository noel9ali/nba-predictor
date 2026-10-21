import { open, done, close, check, report, shot, scrollTo, WIDTHS, intersects } from './lib.mjs';

const SCENES = ['live', 'final', 'nobets'];

async function testDeadSpace() {
  // Record baseline heights at 400px before fix
  const baseline400 = {};

  for (const w of WIDTHS) {
    for (const scene of SCENES) {
      const p = await open(`/?sample=1&scene=${scene}`, w);
      await scrollTo(p, '[data-testid=grid]', 1600);

      const tickets = await p.$$('.ticket');
      for (let i = 0; i < Math.min(2, tickets.length); i++) {
        const ticket = tickets[i];

        // Get all rectangles using evaluate
        const rects = await p.evaluate(ticketEl => {
          const ticketRect = ticketEl.getBoundingClientRect();
          const stub = ticketEl.querySelector('.stub');
          const body = ticketEl.querySelector('.ticket__body');
          const noEl = ticketEl.querySelector('.stub .no');
          const match = ticketEl.querySelector('.match');
          const foot = ticketEl.querySelector('.foot');
          const stamp = ticketEl.querySelector('.stamp');

          const result = {
            ticket: ticketRect.toJSON(),
            stub: stub ? stub.getBoundingClientRect().toJSON() : null,
            body: body ? body.getBoundingClientRect().toJSON() : null,
            no: noEl ? noEl.getBoundingClientRect().toJSON() : null,
            match: match ? match.getBoundingClientRect().toJSON() : null,
            foot: foot ? foot.getBoundingClientRect().toJSON() : null,
            stamp: stamp ? stamp.getBoundingClientRect().toJSON() : null,
            bodyChildren: body ? Array.from(body.children).map(el => el.getBoundingClientRect().toJSON()) : []
          };
          return result;
        }, ticket);

        const key = `${w}px ${scene} ticket ${i+1}`;
        const { ticket: ticketRect, stub: stubRect, body: bodyRect, no: noRect, match: matchRect, foot: footRect, stamp: stampRect, bodyChildren } = rects;

        if (w === 400) {
          // Record baseline height for 400px before changes
          if (!baseline400[key]) {
            baseline400[key] = ticketRect.height;
          }
        }

        if (w >= 768) {
          // Check dead space: distance from last body child's bottom to ticket's bottom <= 20px
          if (bodyChildren.length > 0) {
            const maxChildBottom = Math.max(...bodyChildren.map(c => c.bottom));
            const deadSpace = ticketRect.bottom - maxChildBottom;
            check(
              `${key}: dead space ≤ 20px`,
              deadSpace <= 20,
              `deadSpace=${deadSpace.toFixed(1)}px`
            );
          }

          // Check .no positioning and overlap
          if (noRect && stubRect) {
            check(
              `${key}: .no inside stub`,
              stubRect.left <= noRect.left && noRect.right <= stubRect.right &&
                stubRect.top <= noRect.top && noRect.bottom <= stubRect.bottom,
              `noRect=[${noRect.left.toFixed(1)},${noRect.top.toFixed(1)},${noRect.right.toFixed(1)},${noRect.bottom.toFixed(1)}], stubRect=[${stubRect.left.toFixed(1)},${stubRect.top.toFixed(1)},${stubRect.right.toFixed(1)},${stubRect.bottom.toFixed(1)}]`
            );

            // Check .no doesn't overlap other stub children
            const stubChildren = await p.evaluate(stubEl => {
              // Get the .no element to compare against
              const noElement = stubEl.querySelector('.no');
              return Array.from(stubEl.children)
                .filter(el => el !== noElement)  // Exclude the .no element itself
                .map(el => el.getBoundingClientRect().toJSON());
            }, await ticket.$('.stub'));

            let overlaps = 0;
            for (const child of stubChildren) {
              if (intersects(noRect, child)) overlaps++;
            }
            check(
              `${key}: .no doesn't overlap stub children`,
              overlaps === 0,
              `${overlaps} overlaps`
            );
          }

          // Check stamp doesn't overlap .match or .foot (final tickets only)
          // Exact boxes (getBoundingClientRect includes the rotation): no overlap allowed
          if (scene === 'final' && stampRect && matchRect && footRect) {
            const stampIntersectsMatch = intersects(stampRect, matchRect, 0);
            const stampIntersectsFoot = intersects(stampRect, footRect, 0);

            check(
              `${key}: stamp doesn't overlap .match`,
              !stampIntersectsMatch,
              stampIntersectsMatch ? `overlap at [${Math.max(stampRect.left, matchRect.left).toFixed(1)},${Math.max(stampRect.top, matchRect.top).toFixed(1)}]` : ''
            );

            check(
              `${key}: stamp doesn't overlap .foot`,
              !stampIntersectsFoot,
              stampIntersectsFoot ? `overlap at [${Math.max(stampRect.left, footRect.left).toFixed(1)},${Math.max(stampRect.top, footRect.top).toFixed(1)}]` : ''
            );
          }
        }

        // Take screenshots
        if (i < 2) {
          await shot(p, `D5-before-${w}-${scene}`, '[data-testid=grid]');
        }
      }

      check(`${w}px ${scene}: no console errors`, p.errors.length === 0, p.errors.join(' | '));
      await done(p);
    }
  }

  // Check 400px heights unchanged (±1px tolerance)
  for (const w of [400]) {
    for (const scene of SCENES) {
      const p = await open(`/?sample=1&scene=${scene}`, w);
      await scrollTo(p, '[data-testid=grid]', 1600);

      const tickets = await p.$$('.ticket');
      for (let i = 0; i < Math.min(2, tickets.length); i++) {
        const ticket = tickets[i];
        const ticketRect = await p.evaluate(el => el.getBoundingClientRect().toJSON(), ticket);
        const key = `${w}px ${scene} ticket ${i+1}`;
        const baseline = baseline400[key];

        if (baseline) {
          check(
            `${key}: height unchanged`,
            Math.abs(ticketRect.height - baseline) <= 1,
            `baseline=${baseline}, now=${ticketRect.height.toFixed(1)}`
          );
        }
      }
      await done(p);
    }
  }
}

async function testB5() {
  // Verify B5 (notches) still passes
  const WIDTHS_WITH_PHONE = [320, 400, 768, 1440];
  const SCENES = ['live', 'final'];

  for (const w of WIDTHS_WITH_PHONE) {
    for (const scene of SCENES) {
      const p = await open(`/?sample=1&scene=${scene}`, w);
      await scrollTo(p, '[data-testid=grid]', 1600);

      const tickets = await p.$$('.ticket');
      const ticketCount = Math.min(3, tickets.length);

      for (let i = 0; i < ticketCount; i++) {
        const ticket = tickets[i];
        const stub = await ticket.$('.stub');

        if (!stub) continue;

        const beforeContent = await p.evaluate(
          el => getComputedStyle(el, '::before').content,
          stub
        );
        const afterContent = await p.evaluate(
          el => getComputedStyle(el, '::after').content,
          stub
        );

        check(
          `B5-${w}px ${scene} ticket ${i+1}: ::before has content`,
          beforeContent !== 'none',
          `content="${beforeContent}"`
        );
        check(
          `B5-${w}px ${scene} ticket ${i+1}: ::after has content`,
          afterContent !== 'none',
          `content="${afterContent}"`
        );
      }

      await done(p);
    }
  }
}

await testDeadSpace();
await testB5();
await close();
report();
