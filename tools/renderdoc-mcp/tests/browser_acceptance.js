// playwright-cli run-code --filename <this file>, after opening report_fixture.
async (page) => {
  const rows = page.locator('#rows tr');
  if (await rows.count() !== 200) throw new Error('pagination initial');
  const root = page.locator('#hierarchy > details > summary');
  if (!(await root.innerText()).includes('350.0000 ms')) throw new Error('aggregate double count');
  if (await page.locator('#hierarchy details details').count() !== 2) throw new Error('same-name markers merged');
  await page.getByRole('button', {name: 'Show more'}).click();
  if (await rows.count() !== 350) throw new Error('pagination expand');
  await page.getByRole('textbox', {name: 'Filter name / EID'}).fill('Draw <escaped>');
  if (!(await page.locator('#coverage').innerText()).startsWith('350 ')) throw new Error('escaped text filter');
  await page.getByRole('spinbutton', {name: 'Minimum EID'}).fill('100');
  await page.getByRole('spinbutton', {name: 'Maximum EID'}).fill('100');
  if (await rows.count() !== 1) throw new Error('EID range');
  await page.getByRole('combobox', {name: 'Counter', exact: true}).selectOption('2');
  if (!(await rows.innerText()).includes('18446744073709551614')) throw new Error('integer precision');
  await page.getByRole('button', {name: 'Inspect', exact: true}).click();
  await page.getByText('Selected event data', {exact: true}).click();
  if (!(await page.locator('#detail').innerText()).includes('100')) throw new Error('event detail');
  await page.screenshot({path: 'report-ui-acceptance.png'});
  return {pagination: true, markerTotals: true, sameNameMarkers: true, escapedText: true,
          eidRange: true, largeInteger: true, eventDetail: true};
}
