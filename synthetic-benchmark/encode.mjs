import { createReadStream } from 'node:fs';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import bwip from 'bwip-js';

const input = createInterface({ input: createReadStream(process.argv[2]), crlfDelay: Infinity });
for await (const line of input) {
    const sample = JSON.parse(line);
    const symbols = [];
    for (const { encoder, text, options } of sample.symbols) {
        const image = await bwip.toBuffer({
            bcid: encoder, text, scale: 4, backgroundcolor: 'ffffff', ...options,
        });
        symbols.push(image.toString('base64'));
    }
    if (!process.stdout.write(`${JSON.stringify(symbols)}\n`)) {
        await once(process.stdout, 'drain');
    }
}
