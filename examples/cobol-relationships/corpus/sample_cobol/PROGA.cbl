       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGA.
      *
      * Top-level driver. Reads customer record, calls PROGB to
      * validate, then writes result. Uses CUSTOMER-REC layout from
      * the FOO copybook.
      *
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO 'CUSTDATA'
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE.
       01  CUST-RECORD.
           COPY FOO.
       WORKING-STORAGE SECTION.
       01  WS-STATUS         PIC X(02) VALUE SPACES.
       01  WS-VALID-FLAG     PIC X(01) VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT CUST-FILE.
           PERFORM READ-PARA UNTIL WS-STATUS = '10'.
           CALL 'PROGB' USING CUST-RECORD WS-VALID-FLAG.
           CLOSE CUST-FILE.
           STOP RUN.
       READ-PARA.
           READ CUST-FILE
               AT END MOVE '10' TO WS-STATUS
           END-READ.
