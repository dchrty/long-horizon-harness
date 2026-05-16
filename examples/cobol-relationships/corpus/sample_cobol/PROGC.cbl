       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGC.
      *
      * Leaf program — performs the credit lookup. No further CALLs.
      *
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-LOOKUP-RESULT  PIC 9(05) VALUE 00000.
       LINKAGE SECTION.
       01  L-CUST-RECORD.
           COPY BAR.
       01  L-CREDIT-LIMIT    PIC 9(05).
       PROCEDURE DIVISION USING L-CUST-RECORD L-CREDIT-LIMIT.
       MAIN-PARA.
           MOVE 50000 TO WS-LOOKUP-RESULT.
           MOVE WS-LOOKUP-RESULT TO L-CREDIT-LIMIT.
           GOBACK.
