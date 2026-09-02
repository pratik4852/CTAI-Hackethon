# Regenerating the user manual

    cd docs
    npm install docx
    node build_manual.js MEPIQ_User_Manual.docx

Everything in the document is written in `build_manual.js`, so edits belong
there rather than in the .docx — that keeps the manual in version control as
text and reviewable in a diff.
