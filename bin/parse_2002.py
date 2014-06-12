#!/usr/bin/env python

import csv
import re

from openelexdata.us.ia import BaseParser, ParserState, arg_parser
from openelexdata.us.ia.util import get_column_breaks, split_into_columns

contest_re = re.compile(r'(?P<office>Governor) - (Democrat|Iowa Green Party|Republican)')
whitespace_re = re.compile(r'\s{2,}')
number_re = re.compile('^\d+$')

class RootState(ParserState):
    name = 'root'

    def handle_line(self, line):
        m = contest_re.match(line)
        if m:
            self._context['office'] = m.group('office')
            self._context.change_state('result_header')
        elif line.startswith("State of Iowa"):
            self._context.change_state('document_header')
        elif line.startswith("ELECTION:"):
            self._context.change_state('page_header')

class DocumentHeaderState(ParserState):
    name = 'document_header'

    def handle_line(self, line):
        if line.startswith("Secretary of State"):
            self._context.change_state('root')


class PageHeader(ParserState):
    name = 'page_header'

    def enter(self):
        if "Primary" in self._context.current_line:
            self._context['primary'] = True

    def handle_line(self, line):
        m = contest_re.match(line)
        if m:
            self._context['office'] = m.group('office')
            self._context.change_state('result_header')


class ResultHeader(ParserState):
    name = 'result_header'

    def enter(self):
        self._context['header_lines'] = []

    def handle_line(self, line):
        if not line:
            return

        cols = whitespace_re.split(line)
        if len(cols) > 1 and number_re.match(cols[1]):
            self._context.change_state('results')
        else:
            self._context['header_lines'].append(self._context.raw_line)


class Results(ParserState):
    name = 'results'

    def enter(self):
        if self._context.previous_state == 'result_header':
            self._candidates, self._parties = self._parse_header()
            self.handle_line(self._context.current_line)

    def exit(self):
        if self._context.next_state == "root":
            #del self._context['district_num']
            del self._context['header_lines']

    def handle_line(self, line):
        if line.startswith("ELECTION:"):
            self._context.change_state('page_header')
            return

        cols = whitespace_re.split(line)
        if len(cols) < 2:
            return

        jurisdiction = cols[0]
        reporting_level = 'racewide' if jurisdiction == "Totals" else 'county'
        vote_index = 1
        for i in range(len(self._candidates)):
            candidate = self._candidates[i]
            party = self._parties[i]
            if not party and self._context['primary']:
                party = self._parties[0]
            votes = cols[vote_index].replace(',', '')
            vote_index += 1
            self._context.results.append({
                'office': self._context['office'], 
                #'district': self._context['district_num'],
                'candidate': candidate,
                'party': party, 
                'reporting_level': reporting_level, 
                'jurisdiction': jurisdiction,
                'votes': votes, 
            })

        if cols[0] == "Totals":
            self._context.change_state('root')

    def _parse_header(self, header_lines=None):
        #candidate_col_vals = ["Write-In", "Votes", "Totals"]
        party_col_vals = ["Democratic", "Iowa Green", "Party", "Republican"]
        if header_lines is None:
            header_lines = self._context['header_lines']
        self._breaks = get_column_breaks(header_lines)
        header_cols = split_into_columns(header_lines, self._breaks)

        parties = ['']*len(header_cols[0])
        candidates = ['']*len(header_cols[0])
        for row in header_cols:
            for i in range(len(row)):
                col = row[i]
                if not col:
                    continue

                if col in party_col_vals:
                    sep = " " if parties[i] else ""
                    parties[i] += sep + col
                else:
                    sep = " " if candidates[i] else ""
                    candidates[i] += sep + col

        return candidates, parties


class ResultParser(BaseParser):
    def __init__(self, infile):
        super(ResultParser, self).__init__(infile)
        self._register_state(RootState(self))
        self._register_state(DocumentHeaderState(self))
        self._register_state(PageHeader(self))
        self._register_state(ResultHeader(self))
        self._register_state(Results(self))
        self._current_state = self._get_state('root')

        self['primary'] = False


fields = [
    'office',
    'district',
    'candidate',
    'party',
    'reporting_level',
    'jurisdiction',
    'votes',
]

if __name__ == "__main__":
    args = arg_parser.parse_args()

    parser = ResultParser(args.infile)
    writer = csv.DictWriter(args.outfile, fields)
    try:
        parser.parse()
    except Exception:
        msg = "Exception at line {} of input file, in state {}\n"
        print(msg.format(parser.line_number, parser.current_state.name))
        print("Line: {}".format(parser.current_line))
        raise

    writer.writeheader()
    for result in parser.results:
        writer.writerow(result)