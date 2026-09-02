# CTD 2026 AI Hackathon

## Problem Statement

### Design Management for MEP with AI

Develop an AI solution capable of understanding Mechanical, Electrical & Plumbing 2D drawings by detecting and interpreting MEP objects. The solution should create a foundation for downstream workflows such as quantity takeoff, constructability review, drawing review, and change analysis.

**Dataset Link:** [Access the Dataset](https://drive.google.com/file/d/1b1tWKVUQy2fEquU9Z6urx5CFBlbFnEdx/view)

## Level 1 — Quantifiable Object Detection & Counting

**Objective: ** Detect, identify, and count the specified quantifiable MEP components in Mechanical and Electrical drawings.

### Expected Deliverables

- Detect the specified quantifiable objects in Mechanical and Electrical 2D drawings (object/component details will be provided with the dataset).
- Identify and classify each detected MEP component.
- Generate bounding boxes or segmentation masks for detected objects, along with confidence scores.
- Provide an accurate count of each specified component type for each drawing/sheet.
- Extract relevant object metadata and generate structured output (JSON/CSV) containing object type, location, confidence, and counts.
- Support multiple symbols/components and handle different drawing layouts and sheet scales reasonably well.
- Use the detection and count outputs to support Drawing Review, Design Validation, and quantity takeoff based on the checklist provided.

### Evaluation Pointers

- Detection and classification accuracy (Precision/Recall/mAP).
- Object count accuracy for the specified Mechanical and Electrical components.
- Ability to generalize across drawings, layouts, symbols, and scales.
- Practical usefulness and accuracy of generated insights for drawing review and design validation.
- Reduction in manual effort for quantity takeoff and review workflows.
- Speed of inference and quality of prediction visualizations/reports.

## Level 2 — Linear Measurement

**Objective:** Detect linear MEP objects and accurately measure AC vent lengths in Mechanical drawings and pipe lengths in Plumbing drawings.

### Expected Deliverables

- Detect and trace AC vents in Mechanical drawings and pipes in Plumbing drawings as linear objects (object details will be provided with the dataset).
- Identify the relevant linear object/run and maintain continuity across the drawing where possible.
- Calculate the length of each detected AC vent run and Plumbing pipe, using the drawing scale appropriately.
- Provide total measured lengths by object/run and by drawing/sheet.
- Extract relevant metadata and generate structured output (JSON/CSV) containing object type, location/path, and measured length.
- Detect connectivity or relationships between linear components where possible.
- Use the measured outputs to support Drawing Review, Design Validation, and linear quantity takeoff based on the checklist provided.

### Evaluation Pointers

- Accuracy and continuity of detected linear objects.
- Linear length measurement accuracy for AC vents and Plumbing pipes.
- Correct handling of drawing scale and robustness across layouts.
- Connectivity/relationship detection where applicable.
- Practical usefulness and accuracy of generated insights for drawing review and design validation.
- Reduction in manual effort for linear measurement and review workflows.
- Quality of structured output, visualization, reports, or dashboards.

## Level 3 — Intelligent Assistant (AI Copilot)

**Objective:** Build an AI assistant that interacts with engineering data.

### Expected Deliverables

Examples include:

- Natural language querying
- Explain detected issues
- Generate engineering summaries
- Interactive review interface
- Create a bot which can help to chat and gain insights from drawings

### Evaluation Pointers

- User experience
- Reasoning quality
- Explainability
- Engineering relevance
- End-to-end workflow integration

## ⭐ Level 4 — Cherry on Top (Innovation Award)

This level is optional and intended to recognize exceptional innovation beyond the core problem.

### Examples

- Generate corrective design recommendations
- Identify engineering/design risks
- Enable cross-discipline MEP coordination
- Integrate with BIM/Revit/IFC workflows
- Detect spatial and system clashes
- Incorporate user feedback for model refinement
- Apply multi-modal reasoning across drawings, specifications, and codes

### Bonus Evaluation

- Innovation
- Technical complexity
- Industry impact
- Scalability
- Future Readiness

## Evaluation Weightage

| Level | Focus | Weight |
|---|---|---:|
| Level 1 | Quantifiable Object Detection & Counting | 35% |
| Level 2 | Linear Measurement Accuracy | 40% |
| Level 3 | AI Experience & Usability | 15% |
| ⭐ Level 4 | Innovation Bonus | +10% |

## Progression

This progression mirrors how AI products mature in practice:

1. **Detect & Count** (Quantifiable Objects)
2. **Measure** (Linear Objects)
3. **Assist** (AI Copilot)
4. **Transform** (Industry Innovation)

## Suggested Ways of Final Submission

Each team will be provided with a dedicated GitHub repository, which will serve as the final submission location.

Participants must push the complete source code, dependencies, and required instructions to this repository. The solution may be implemented as either:

- A **Jupyter Notebook (.ipynb)** containing the complete solution.
- A **Deployed web application** demonstrating the solution end-to-end.

For deployed applications, the corresponding application source code and setup/deployment instructions must also be included in the team’s GitHub repository.
