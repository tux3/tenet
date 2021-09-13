import bisect
import collections

#-----------------------------------------------------------------------------
# analysis.py -- Trace Analysis
#-----------------------------------------------------------------------------
#
#    This file should contain logic to further process, augment, optimize or
#    annotate Tenet traces when a binary analysis framework such as IDA /
#    Binary Ninja is available to a trace reader.
#
#    As of now (v0.2) the only added analysis we do is to try and map
#    ASLR'd trace addresses to executable opened in the database.
#
#    In the future, I imagine this file will be used to indexing events
#    such as function calls, returns, entry and exit to unmapped regions,
#    service pointer annotations, and much more.
#

class TraceAnalysis(object):
    """
    A high level, debugger-like interface for querying Tenet traces.
    """

    def __init__(self, trace, dctx):
        self._dctx = dctx
        self._trace = trace
        self._remapped_regions = []
        self._unmapped_entry_points = []
        self._analyze()

    #-------------------------------------------------------------------------
    # Public
    #-------------------------------------------------------------------------

    def rebase_pointer(self, address):
        """
        Return a rebased version of the given address, if one exists.
        """
        for m1, m2 in self._remapped_regions:
            #print(f"m1 start: {m1[0]:08X} address: {address:08X} m1 end: {m1[1]:08X}")
            #print(f"m2 start: {m2[0]:08X} address: {address:08X} m2 end: {m2[1]:08X}")
            if m1[0] <= address <= m1[1]:
               return address + (m2[0] - m1[0])
            if m2[0] <= address <= m2[1]:
               return address - (m2[0] - m1[0])
        return address

    def get_prev_mapped_idx(self, idx):
        """
        Return the previous idx to fall within a mapped code region.
        """
        index = bisect.bisect_right(self._unmapped_entry_points, idx) - 1
        try:
            return self._unmapped_entry_points[index]
        except IndexError:
            return -1

    #-------------------------------------------------------------------------
    # Analysis
    #-------------------------------------------------------------------------

    def _analyze(self):
        """
        Analyze the trace against the binary loaded by the disassembler.
        """
        self._analyze_aslr()
        self._analyze_unmapped()

    def _analyze_aslr(self):
        """
        Analyze trace execution to resolve ASLR mappings against the disassembler.
        """
        dctx, trace = self._dctx, self._trace

        # get instruction addresses from disassembler
        instuction_addresses = dctx.get_instruction_addresses()

        # bucket the disas addresses based on non-aslr'd bits
        binary_buckets = collections.defaultdict(list)
        for address in instuction_addresses:
            bits = address & 0xFFF
            binary_buckets[bits].append(address)

        # get the set of ips from the trace
        trace_addresses = trace.ip_addrs

        # keep trace addresses that 'seem' interesting
        trace_buckets = collections.defaultdict(list)
        for executed_address in trace_addresses:
            bits = executed_address & 0xFFF
            if bits not in binary_buckets:
                continue
            trace_buckets[bits].append(executed_address)

        slide_buckets = collections.defaultdict(list)
        for bits, instruction_addresses in binary_buckets.items():
            for executed_address in trace_buckets[bits]:
                for address in instruction_addresses:
                    distance = address - executed_address
                    slide_buckets[distance].append(executed_address)

        hits = []
        for slide, executed_addresses in slide_buckets.items():
            hits.append((len(executed_addresses), slide))

        hits.sort(reverse=True)

        #for num_executed, slide in hits:
        #    print(f"{num_executed} items, slide {slide:08X}")
        #for address in sorted(slide_buckets[hits[0][1]]):
        #    print(f"Executed: {address:08X} --> {address + hits[0][1]:08X}")

        # fetch the top hit
        _, slide = hits[0]

        m1 = [instuction_addresses[0], instuction_addresses[-1]]

        if slide < 0:
            m2 = [m1[0] - slide, m1[1] - slide]
        else:
            m2 = [m1[0] + slide, m1[1] + slide]

        self._remapped_regions.append((m1, m2))

        #print(f"BIN ADDRESSES: {len(instuction_addresses)}")
        #print(f"TRC ADDRESSES: {len(trace_addresses)}")
        #print(f"INT ADDRESSES: {len(interesting_addresses)}")

    def _analyze_unmapped(self):
        """
        Analyze trace execution to identify entry/exit to unmapped segments.
        """
        trace, ips = self._trace, self._trace.ip_addrs
        lower_mapped, upper_mapped = self._remapped_regions[0][1]

        #
        # for speed, pull out the 'compressed' ip indexes that matched mapped
        # (known) addresses within the disassembler context
        #

        mapped_ips = set()
        for i, address in enumerate(ips):
            if lower_mapped <= address <= upper_mapped:
                mapped_ips.add(i)

        last_good_idx = 0
        unmapped_entries = []

        # loop through each segment in the trace
        for seg in trace.segments:
            seg_ips = seg.ips
            seg_base = seg.base_idx

            # loop through each executed instruction in this segment
            for relative_idx in range(0, seg.length):
                compressed_ip = seg_ips[relative_idx]

                # the current instruction is in an unmapped region
                if compressed_ip not in mapped_ips:

                    # if we were in a known/mapped region previously, then save it
                    if last_good_idx:
                        unmapped_entries.append(last_good_idx)
                        last_good_idx = 0

                # if we are in a good / mapped region, update our current idx
                else:
                    last_good_idx = seg_base + relative_idx

        #for idx in unmapped_entries:
        #    print(f"Analysis: Unmapped @ IDX {idx:,}")

        #print(f" - Unmapped Entry Points: {len(unmapped_entries)}")
        self._unmapped_entry_points = unmapped_entries
