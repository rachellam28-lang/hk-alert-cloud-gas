import re

with open('ccass.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Fix broken onclick attributes
# From: onclick="toggleFilter("all")"  (broken HTML - inner quotes close outer)
# To:   onclick="toggleFilter('all')"  (use single quotes inside)

html = html.replace('onclick="toggleFilter("all")"', "onclick=\"toggleFilter('all')\"")
html = html.replace('onclick="toggleFilter("up")"', "onclick=\"toggleFilter('up')\"")
html = html.replace('onclick="toggleFilter("dn")"', "onclick=\"toggleFilter('dn')\"")
html = html.replace('onclick="toggleFilter("concentrated")"', "onclick=\"toggleFilter('concentrated')\"")
html = html.replace('onclick="toggleFilter("placement")"', "onclick=\"toggleFilter('placement')\"")
html = html.replace('onclick="toggleFilter("rights")"', "onclick=\"toggleFilter('rights')\"")
html = html.replace('onclick="toggleFilter("small_mc")"', "onclick=\"toggleFilter('small_mc')\"")
html = html.replace('onclick="toggleFilter("mid_mc")"', "onclick=\"toggleFilter('mid_mc')\"")
html = html.replace('onclick="toggleFilter("large_mc")"', "onclick=\"toggleFilter('large_mc')\"")

with open('ccass.html', 'w', encoding='utf-8') as f:
    f.write(html)

print('Done! All filter onclick fixed.')
