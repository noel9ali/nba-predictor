// A5: "Next up" never points to a game whose tip time has passed.
import { open, done, close, check, report, shot, WIDTHS } from './lib.mjs';

const SCENE_CLOCKS = {
  live: '9:05 PM',
  nextup: '6:40 PM',
  sofar: '10:40 PM',
  edges: '10:50 PM',
  feeddown: '9:09 PM',
  replay: '9:05 PM'
};

function parseET(timeStr) {
  // Parse "7:00 PM" format, assuming ET (UTC-5)
  const [time, period] = timeStr.split(' ');
  let [h, m] = time.split(':').map(Number);
  if (period === 'PM' && h !== 12) h += 12;
  if (period === 'AM' && h === 12) h = 0;
  return h * 60 + m;  // minutes since midnight ET
}

function timeAfter(tipStr, sceneStr) {
  const tipMins = parseET(tipStr);
  const sceneMins = parseET(sceneStr);
  return tipMins > sceneMins;
}

async function testScene(scene) {
  const sceneNow = SCENE_CLOCKS[scene];

  for (const w of WIDTHS) {
    const p = await open(`/?sample=1&scene=${scene}`, w);
    const hero = await p.$('[data-testid=hero]');
    const heroText = await hero.textContent();

    // Check no console errors
    check(`${scene}/${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

    // If "Next up:" is present, the time should be after the scene clock
    if (heroText.includes('Next up:')) {
      // Parse the time from "Next up: TEAM +odds at TIME, edge"
      const match = heroText.match(/Next up:.*at\s+([0-9:]+\s+[AP]M)/);
      if (match) {
        const tipTime = match[1];
        check(`${scene}/${w}: "Next up" time is after scene clock`, timeAfter(tipTime, sceneNow), `${tipTime} vs ${sceneNow}`);
      } else {
        check(`${scene}/${w}: "Next up" time is parseable`, false, `Could not parse time from: ${heroText}`);
      }
    }

    // Regression: nextup scene should always have "Next up"
    if (scene === 'nextup') {
      check(`${scene}/${w}: nextup has "Next up:"`, heroText.includes('Next up:'), heroText);
    }

    // feeddown hero text should start with "The model found"
    if (scene === 'feeddown') {
      check(`${scene}/${w}: feeddown starts with "The model found"`, heroText.startsWith('The model found'), heroText);
    }

    await shot(p, `A5-${w}`, '[data-testid=lede]');
    await done(p);
  }
}

// Test all scenes
const testScenes = ['live', 'nextup', 'sofar', 'edges', 'feeddown', 'replay'];
for (const s of testScenes) {
  await testScene(s);
}

await close();
report();
