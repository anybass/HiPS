#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
This script processes all pdfs in a folder specified in the variable directory.

For the whole pdf, one xml is created. 
"""

import subprocess
import os
import re
import shutil
import traceback
directory="../data/PDFs/"
print("The following files are going to be processed:")
for fi in os.listdir(directory):
    if fi.endswith('.pdf'):
       print(fi) 
       subprocess.call('pdftohtml -i "%s" -xml "%s"' %(str(directory+fi), str("./xml/"+fi.strip(".pdf")+".xml")), shell=True)
     
