# :closed_book: HiPS: Hierarchical PDF Segmentation :closed_book:
The goal of this project is to create a prototype which is focusing on structural section parsing of PDF textbooks :book:.

PDF metadata from the Table of Contents (TOC) are used to match headings in the fulltext with various strategies, such as regex or making use of the structural tags in the XML file (that we converted the PDF into). 
Then, we assign a hierarchy level (1-7) to the headings. The output can be used for knowledge engineering (e.g., finding entities sharing a section and analyzing their relationship).

Here, you will find:
<ul>
  <li> 📚 The code for reproducing our experiments</li>
  <li> 📚 The ground truth dataset consisting of textbooks full of headings</li>
  <li> 📚 An issue tracker for the dataset</li>
</ul>

## Dataset
You can find the dataset here:
- The [Original PDF files](./data/PDFs/) (see [attribution](./data/data_sources.csv) ) and [license information]((LICENSE\_DATA.md)) 
- The [Ground Truth Dataset](./data/GT_TOCs/), with the following format:
  - Level, Heading, Page
    
## Steps for the Reproduction of the Experiments
### TOC-based PageParser
1. Make sure you have poppler-utils installed, including [pdftohtml](https://manpages.debian.org/testing/poppler-utils/pdftohtml.1.en.html)
2. [pdftoxml.py](./toc-based-page-parser/pdftoxml.py)
3. [toc_processing_segmentation.ipynb](./toc-based-page-parser/toc_processing_segmentation.ipynb)

### Pdfstructure
1. Get the repo from here: [https://github.com/ChrizH/pdfstructure](https://github.com/ChrizH/pdfstructure)
2. Replicate the folder structure from this repository, and insert the current code of pdfstructure in the folder: [./pdfstructure-master/pdfstructure/](./pdfstructure-master/pdfstructure/)
3. Fix the bug that may still be in pdfminer (otherwise almost no PDF will process). Follow the instruction in [./pdfstructure-master/bugfixing_modification_in_pdfminer.txt](./pdfstructure-master/bugfixing_modification_in_pdfminer.txt).
4. [extract_structure.ipynb](./pdfstructure-master/extract_structure.ipynb)

### Evaluation 
1. [evaluate_hierarchies.ipynb](evaluate_hierarchies.ipynb) (it is important to run this evaluation before evaluate_toc.ipynb)
2. [evaluate_toc.ipynb](evaluate_toc.ipynb)
3. [evaluate_segments.ipynb](evaluate_segments.ipynb)

### Issue Tracker
- Please report any inconsistencies or doubtful ground truth entries as a regular repository issue. 

### Environment Information
This code was tested with Python 3.11 on Xubuntu 22.04.4 LTS x86_64 

## License
The content of this project itself is licensed under the [Creative Commons Attribution-NonCommercial 4.0 International license](LICENSE_DATA.md), and the underlying source code used to format and display that content is licensed under the [MIT license](LICENSE).
