/// Bitmask adjacency for fast set intersections (n <= 1024).
pub const MAX_BITSET_NODES: usize = 1024;

const WORDS: usize = MAX_BITSET_NODES / 64;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct BitMask {
    bits: [u64; WORDS],
}

impl BitMask {
    #[inline]
    pub fn empty() -> Self {
        Self::default()
    }

    #[inline]
    pub fn all(n: usize) -> Self {
        let mut mask = Self::empty();
        for v in 0..n {
            mask.set(v);
        }
        mask
    }

    #[inline]
    pub fn set(&mut self, v: usize) {
        self.bits[v / 64] |= 1u64 << (v % 64);
    }

    #[inline]
    pub fn clear(&mut self, v: usize) {
        self.bits[v / 64] &= !(1u64 << (v % 64));
    }

    #[inline]
    pub fn test(&self, v: usize) -> bool {
        (self.bits[v / 64] & (1u64 << (v % 64))) != 0
    }

    #[inline]
    pub fn is_empty(&self) -> bool {
        self.bits.iter().all(|&w| w == 0)
    }

    #[inline]
    pub fn count(&self) -> u32 {
        self.bits.iter().map(|w| w.count_ones()).sum()
    }

    #[inline]
    pub fn and(self, other: Self) -> Self {
        let mut out = Self::empty();
        for i in 0..WORDS {
            out.bits[i] = self.bits[i] & other.bits[i];
        }
        out
    }

    #[inline]
    pub fn and_assign(&mut self, other: &Self) {
        for i in 0..WORDS {
            self.bits[i] &= other.bits[i];
        }
    }

    #[inline]
    pub fn or_assign(&mut self, other: &Self) {
        for i in 0..WORDS {
            self.bits[i] |= other.bits[i];
        }
    }

    #[inline]
    pub fn and_not_assign(&mut self, other: &Self) {
        for i in 0..WORDS {
            self.bits[i] &= !other.bits[i];
        }
    }

    /// Lowest set bit index, or None if empty.
    #[inline]
    pub fn lowest_bit(&self) -> Option<usize> {
        for (wi, &word) in self.bits.iter().enumerate() {
            if word != 0 {
                return Some(wi * 64 + word.trailing_zeros() as usize);
            }
        }
        None
    }

    #[inline]
    pub fn clear_lowest(&mut self) {
        if let Some(v) = self.lowest_bit() {
            self.clear(v);
        }
    }

    pub fn iter_bits(self) -> BitIter {
        BitIter { mask: self, word_idx: 0, word: self.bits[0] }
    }

    pub fn vertices(self) -> Vec<usize> {
        self.iter_bits().collect()
    }
}

pub struct BitIter {
    mask: BitMask,
    word_idx: usize,
    word: u64,
}

impl Iterator for BitIter {
    type Item = usize;

    fn next(&mut self) -> Option<Self::Item> {
        loop {
            if self.word != 0 {
                let bit = self.word.trailing_zeros() as usize;
                let vertex = self.word_idx * 64 + bit;
                self.word &= self.word - 1;
                return Some(vertex);
            }
            self.word_idx += 1;
            if self.word_idx >= WORDS {
                return None;
            }
            self.word = self.mask.bits[self.word_idx];
        }
    }
}

pub fn neighbor_sets_to_masks(neighbor_sets: &[Vec<usize>]) -> Vec<BitMask> {
    neighbor_sets
        .iter()
        .map(|neighbors| {
            let mut mask = BitMask::empty();
            for &v in neighbors {
                mask.set(v);
            }
            mask
        })
        .collect()
}

pub fn mask_intersection(masks: &[BitMask]) -> BitMask {
    if masks.is_empty() {
        return BitMask::empty();
    }
    let mut result = masks[0];
    for mask in &masks[1..] {
        result = result.and(*mask);
    }
    result
}

pub fn mask_degree(mask: BitMask) -> u32 {
    mask.count()
}
