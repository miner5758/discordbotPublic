You will be given a URL. The page may contain information about a program, company, position, or opportunity.

Your task is to extract **five key pieces of information** from the page and return them as a single comma-separated string. This link is only a test. You will be given different links in the future, but the instructions below will always apply.

⚠️ INSTRUCTIONS (READ CAREFULLY):

DO NOT:

   - Guess, infer, or add any information not explicitly present on the page.
   - Use hidden content, metadata not visible on the page, or content that requires interaction (clicks, scrolling).
   - Give me a result that is not in the format I specified, absoulty DO NOT do this AT ALL. if it is not in the format TRY AGAIN
   - List location in any field. Do not take location into consideration at all. Also don't list things like seasons and date, EX. Fall 2024
   - Just list the name of the field for the field value. Be dedicated to this task
   - USE ANY WORDS NOT FOUND IN THE PAGE/URL PROVIDED. ANY WORD NOT FOUND IN THE PAGE SHOULD NOT BE USED

DO:
   - Read the webpage VERY CAREFULLY and make sure you get every piece of info you possible can from it
   - Remember that all the information you need can be found in the link. please don't make stuff up.

Extract the following five fields, in order:

1. **name** – The full name of the program, company, position, or opportunity.
   - Look for the **exact job title, internship title, or program name** on the page. This is often found in page headings, main titles, or metadata.
   - Prioritize titles that include keywords common in job and internship positions such as: intern, internship, analyst, research, associate, trainee, fellow, specialist, or similar.
   - If the title does not include the company name, prepend the company name before the title, separated by a space.
   - Use only information explicitly present on the page; do not guess or add any information.
   - If no clear position or program title is found, use the company name alone.
   - Usually isn't going to be a full-time position. Try not to list full time positions and ignore them unless its clear that it is a full-time position 
   ⚠️ Do NOT use commas anywhere in this name (use other punctuation like periods or semicolons instead) because the output must be comma-separated and unambiguous.

2. **summary** – In your own words, write a brief, clear summary that explains:
   - What the opportunity is.
   - Who it's for (e.g. students, interns, recent grads).
   - What someone would do or gain by participating.
   - What work is done in the oppotunity. Make sure you list specific tools and projects mentioned in the page.
   - The summary should be 4-6 setnences long.
   - Be detailed with your summary, don't cheap out.
   ⚠️ Do **not** copy and paste. Summarize the key info someone would need to decide whether to apply. Make sure the summary is similar to the orginal text found on the page
   ⚠️ Do NOT use commas anywhere in this summary (use other punctuation like periods or semicolons instead) because the output must be comma-separated and unambiguous.
   ⚠️ Do NOT base your summary off the name, only base it off the url/page so that we reduce errors

3. **application/opportunity/program_open_date** – When the application/opportunity/program opens.
   - If not stated, return `"N/A"`.
   - Write it in Month Day year format. Ex. August #th, 2025

4. **application/opportunity/program_close_date** – When the application/opportunity/program closes.
   - If not stated, return `"N/A"`.
   - Write it in Month Day year format. Ex. August #th, 2025
   - Don't put an unrealsic date. for example the close date can't be in 2024 if we are currently in 2025

5. **link** – Always return the exact URL you were given.

📌 OUTPUT FORMAT (STRICT):
Return a **single line of comma-separated values** in this exact order:
`name,summary,application/opportunity/program_open_date,application/opportunity/program_close_date,link`

DO NOT include:
- Quotation marks
- Field labels like "name:"
- Brackets, dictionary formatting, or line breaks
- Any text before or after the result

📌 MISSING FIELDS:
If any field (except the link) is missing or unclear, return `"N/A"` for that field.